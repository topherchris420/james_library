//! ZeroClaw P2P Networking Module
//!
//! Provides peer-to-peer networking capabilities including:
//! - Gossipsub for pub/sub messaging
//! - Kademlia for DHT-based peer discovery
//! - mDNS for local network discovery
//! - Ping protocol for peer health monitoring
//! - Relay/circuit relay for NAT traversal
//! - Peer connection state tracking and metrics

use anyhow::{Context, Result};
use futures_util::StreamExt;
use libp2p::{
    autonomy::{Behaviour as AutonatBehaviour, Event as AutonatEvent},
    core::connected_point::ConnectedPoint,
    dcutr::{Behaviour as DcutrBehaviour, Event as DcutrEvent},
    gossipsub::{self, IdentTopic, MessageAuthenticity, SubscriptionError},
    identify::{Behaviour as IdentifyBehaviour, Config as IdentifyConfig, Event as IdentifyEvent},
    identity,
    kad::{
        store::MemoryStore, Behaviour as Kademlia, Event as KademliaEvent, KBucketKey, PeerRecord,
        RecordKey,
    },
    mdns::{Behaviour as MdnsBehaviour, Event as MdnsEvent},
    multiaddr::Protocol,
    noise,
    ping::{Behaviour as PingBehaviour, Config as PingConfig, Event as PingEvent, Priority},
    relay::{client::Behaviour as RelayClient, Event as RelayEvent},
    swarm::{NetworkBehaviour, SwarmEvent},
    tcp, yamux, Multiaddr, PeerId, SwarmBuilder,
};
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tokio::sync::{mpsc, RwLock};

pub const RESEARCH_TOPIC: &str = "research/acoustic-physics";
const DEFAULT_LISTEN_ADDR: &str = "/ip4/127.0.0.1/tcp/0";
const PING_INTERVAL: Duration = Duration::from_secs(30);
const PEER_EXPIRY: Duration = Duration::from_secs(300);

static RUNTIME: tokio::sync::OnceCell<Arc<P2pRuntime>> = tokio::sync::OnceCell::const_new();

/// P2P Runtime shared state
pub struct P2pRuntime {
    sender: mpsc::Sender<P2pCommand>,
    peers: Arc<RwLock<PeerState>>,
    stats: Arc<RwLock<P2pStats>>,
}

/// Commands for P2P runtime
enum P2pCommand {
    Publish { topic: String, data: Vec<u8> },
    Subscribe { topic: String },
    Unsubscribe { topic: String },
    GetPeers,
    GetStats,
    Shutdown,
}

/// Peer connection state
#[derive(Debug, Clone, Serialize)]
pub struct PeerInfo {
    pub peer_id: String,
    pub addresses: Vec<String>,
    pub connected: bool,
    pub last_ping: Option<u64>,
    pub last_pong: Option<u64>,
    pub latency_ms: Option<u64>,
    pub discovered_via: String,
    pub first_seen: u64,
}

/// Peer state tracker
#[derive(Debug)]
pub struct PeerState {
    peers: HashMap<PeerId, PeerInfo>,
    local_peers: HashSet<PeerId>,
}

impl Default for PeerState {
    fn default() -> Self {
        Self {
            peers: HashMap::new(),
            local_peers: HashSet::new(),
        }
    }
}

/// P2P statistics
#[derive(Debug, Clone, Default, Serialize)]
pub struct P2pStats {
    pub messages_published: u64,
    pub messages_received: u64,
    pub peers_connected: u64,
    pub peers_discovered: u64,
    pub pings_sent: u64,
    pub pongs_received: u64,
    pub start_time: u64,
}

/// Research topic message payload
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AdvisoryExperimentResult {
    pub ts: u64,
    pub node: String,
    pub topic: &'static str,
    pub advisory: bool,
    pub body: String,
}

/// Combined P2P behaviour
#[derive(NetworkBehaviour)]
#[behaviour(to_swarm = "P2pEvent")]
struct P2pBehaviour {
    gossipsub: gossipsub::Behaviour,
    kademlia: Kademlia<MemoryStore>,
    mdns: MdnsBehaviour,
    ping: PingBehaviour,
    autonat: AutonatBehaviour,
    relay_client: RelayClient,
    identify: IdentifyBehaviour,
    dcutr: DcutrBehaviour,
}

/// P2P events from behaviours
#[derive(Debug)]
enum P2pEvent {
    Gossip(gossipsub::Event),
    Kad(KademliaEvent),
    Mdns(MdnsEvent),
    Ping(PingEvent),
    Autonat(AutonatEvent),
    Relay(RelayEvent),
    Identify(IdentifyEvent),
    Dcutr(DcutrEvent),
}

impl From<gossipsub::Event> for P2pEvent {
    fn from(v: gossipsub::Event) -> Self {
        Self::Gossip(v)
    }
}
impl From<KademliaEvent> for P2pEvent {
    fn from(v: KademliaEvent) -> Self {
        Self::Kad(v)
    }
}
impl From<MdnsEvent> for P2pEvent {
    fn from(v: MdnsEvent) -> Self {
        Self::Mdns(v)
    }
}
impl From<PingEvent> for P2pEvent {
    fn from(v: PingEvent) -> Self {
        Self::Ping(v)
    }
}
impl From<AutonatEvent> for P2pEvent {
    fn from(v: AutonatEvent) -> Self {
        Self::Autonat(v)
    }
}
impl From<RelayEvent> for P2pEvent {
    fn from(v: RelayEvent) -> Self {
        Self::Relay(v)
    }
}
impl From<IdentifyEvent> for P2pEvent {
    fn from(v: IdentifyEvent) -> Self {
        Self::Identify(v)
    }
}
impl From<DcutrEvent> for P2pEvent {
    fn from(v: DcutrEvent) -> Self {
        Self::Dcutr(v)
    }
}

/// Initialize P2P runtime
pub async fn ensure_runtime_started() -> Result<()> {
    if !p2p_enabled() {
        return Ok(());
    }

    let _ = RUNTIME.get_or_try_init(init_p2p_runtime).await?;
    Ok(())
}

async fn init_p2p_runtime() -> Result<Arc<P2pRuntime>> {
    let listen_addr: Multiaddr = std::env::var("ZEROCLAW_P2P_LISTEN_ADDR")
        .unwrap_or_else(|_| DEFAULT_LISTEN_ADDR.to_string())
        .parse()
        .context("invalid ZEROCLAW_P2P_LISTEN_ADDR")?;

    // Generate identity
    let key = identity::Keypair::generate_ed25519();
    let local_peer_id = PeerId::from(key.public());

    // Configure gossipsub
    let topic = IdentTopic::new(RESEARCH_TOPIC);
    let gossip_cfg = gossipsub::ConfigBuilder::default()
        .validation_mode(gossipsub::ValidationMode::Strict)
        .message_id_fn(|msg| {
            use std::collections::hash_map::DefaultHasher;
            use std::hash::{Hash, Hasher};
            let mut h = DefaultHasher::new();
            msg.source.hash(&mut h);
            msg.data.hash(&mut h);
            gossipsub::MessageId::from(h.finish().to_string())
        })
        .build()
        .context("failed to build gossipsub config")?;

    let mut gossipsub =
        gossipsub::Behaviour::new(MessageAuthenticity::Signed(key.clone()), gossip_cfg)
            .context("failed to construct gossipsub")?;
    gossipsub
        .subscribe(&topic)
        .context("failed to subscribe to research topic")?;

    // Configure Kademlia
    let store = MemoryStore::new(local_peer_id);
    let mut kademlia = Kademlia::new(local_peer_id, store);

    // Bootstrap from configured peers
    let bootstrap_addrs = parse_bootstrap_addrs();
    for (peer_id, addr) in &bootstrap_addrs {
        kademlia.add_address(peer_id, addr.clone());
    }

    // Bootstrap Kademlia
    if !bootstrap_addrs.is_empty() {
        kademlia.bootstrap().ok();
    }

    // Configure mDNS for local discovery
    let mdns = MdnsBehaviour::new(identity::Keypair::generate_ed25519(), 8080)
        .context("failed to create mDNS service")?;

    // Configure ping protocol
    let ping = PingBehaviour::new(
        PingConfig::new()
            .with_interval(PING_INTERVAL)
            .with_timeout(Duration::from_secs(10)),
    );

    // Configure autonat for NAT traversal detection
    let autonat = AutonatBehaviour::new(local_peer_id, Default::default());

    // Configure relay client
    let relay_client = RelayClient::new(local_peer_id);

    // Configure identify protocol
    let identify = IdentifyBehaviour::new(
        IdentifyConfig::new("zeroclaw/0.5.0".to_string(), key.public())
            .with_agent_version("ZeroClaw P2P/0.5".to_string()),
    );

    // Configure DCUtR for direct connection upgrade
    let dcutr = DcutrBehaviour::new();

    // Build swarm
    let mut swarm = SwarmBuilder::with_existing_identity(key)
        .with_tokio()
        .with_tcp(
            tcp::Config::default().nodelay(true),
            noise::Config::new,
            yamux::Config::default,
        )
        .context("failed to build tcp transport")?
        .with_behaviour(|_| P2pBehaviour {
            gossipsub,
            kademlia,
            mdns,
            ping,
            autonat,
            relay_client,
            identify,
            dcutr,
        })
        .context("failed to build p2p behaviour")?
        .build();

    // Start listening
    swarm
        .listen_on(listen_addr)
        .context("failed to bind p2p listen address")?;

    // Create channels
    let (cmd_tx, mut cmd_rx) = mpsc::channel::<P2pCommand>(128);
    let peers = Arc::new(RwLock::new(PeerState::default()));
    let stats = Arc::new(RwLock::new(P2pStats {
        start_time: now_unix(),
        ..Default::default()
    }));

    let topic_clone = topic.clone();
    let peers_clone = peers.clone();
    let stats_clone = stats.clone();

    // Spawn P2P event loop
    tokio::spawn(async move {
        let mut interval = tokio::time::interval(PING_INTERVAL);

        loop {
            tokio::select! {
                _ = interval.tick() => {
                    // Periodic ping all known peers
                    let mut swarm = swarm.lock_step();
                    let current_peers: Vec<PeerId> = swarm.connected_peers().copied().collect();

                    for peer_id in current_peers {
                        if let Some(info) = peers_clone.write().await.peers.get_mut(&peer_id) {
                            info.last_ping = Some(now_unix());
                        }
                        swarm.behaviour_mut().ping.ping(peer_id, Priority::High);
                        *stats_clone.write().await.pings_sent += 1;
                    }

                    // Clean up expired peers
                    let now = now_unix();
                    let mut peers = peers_clone.write().await.peers;
                    peers.retain(|_, info| {
                        now.saturating_sub(info.last_pong.unwrap_or(info.first_seen)) < PEER_EXPIRY.as_secs()
                    });
                }
                cmd = cmd_rx.recv() => {
                    match cmd {
                        Some(P2pCommand::Publish { topic, data }) => {
                            let topic = IdentTopic::new(&topic);
                            if let Err(e) = swarm.behaviour_mut().gossipsub.publish(topic, data) {
                                tracing::warn!("publish failed: {}", e);
                            } else {
                                *stats_clone.write().await.messages_published += 1;
                            }
                        }
                        Some(P2pCommand::GetPeers) => {
                            // Response handled via state
                        }
                        Some(P2pCommand::GetStats) => {
                            // Response handled via state
                        }
                        Some(P2pCommand::Shutdown) | None => break,
                        _ => {}
                    }
                }
                event = swarm.select_next_some() => {
                    match event {
                        SwarmEvent::NewListenAddr { address, .. } => {
                            tracing::info!("p2p listening on {}", address);
                        }
                        SwarmEvent::ConnectionEstablished { peer_id, endpoint, .. } => {
                            let conn_info = PeerInfo {
                                peer_id: peer_id.to_string(),
                                addresses: swarm
                                    .listening Addresses()
                                    .iter()
                                    .filter(|a| a.has_p2p())
                                    .map(|a| a.to_string())
                                    .collect(),
                                connected: true,
                                last_ping: None,
                                last_pong: None,
                                latency_ms: None,
                                discovered_via: match endpoint {
                                    ConnectedPoint::Dialer { .. } => "dial".to_string(),
                                    ConnectedPoint::Listener { .. } => "listen".to_string(),
                                },
                                first_seen: now_unix(),
                            };
                            let mut peers = peers_clone.write().await.peers;
                            peers.entry(peer_id).or_insert_with(|| {
                                *stats_clone.write().await.peers_discovered += 1;
                                *stats_clone.write().await.peers_connected += 1;
                                conn_info
                            });
                        }
                        SwarmEvent::ConnectionClosed { peer_id, .. } => {
                            let mut peers = peers_clone.write().await.peers;
                            if let Some(info) = peers.get_mut(&peer_id) {
                                info.connected = false;
                            }
                            *stats_clone.write().await.peers_connected = stats_clone.read().await.peers_connected.saturating_sub(1);
                        }
                        SwarmEvent::Behaviour(P2pEvent::Gossip(gossipsub::Event::Message { message, .. })) => {
                            let source = message.source.map_or_else(|| "unknown".to_string(), |p| p.to_string());
                            tracing::debug!("p2p gossip from {} on {}", source, message.topic);
                            *stats_clone.write().await.messages_received += 1;
                        }
                        SwarmEvent::Behaviour(P2pEvent::Ping(PingEvent::Pong { peer, latency })) => {
                            if let Some(info) = peers_clone.write().await.peers.get_mut(&peer) {
                                info.last_pong = Some(now_unix());
                                info.latency_ms = Some(latency.as_millis() as u64);
                            }
                            *stats_clone.write().await.pongs_received += 1;
                        }
                        SwarmEvent::Behaviour(P2pEvent::Mdns(MdnsEvent::Discovered(addrs))) => {
                            for (peer_id, addr) in addrs {
                                if !peers_clone.read().await.local_peers.contains(&peer_id) {
                                    tracing::debug!("mDNS discovered peer: {}", peer_id);
                                    peers_clone.write().await.local_peers.insert(peer_id);

                                    // Add to kademlia for broader discovery
                                    swarm.behaviour_mut().kademlia.add_address(&peer_id, addr);
                                }
                            }
                        }
                        SwarmEvent::Behaviour(P2pEvent::Mdns(MdnsEvent::Expired(addrs))) => {
                            for (peer_id, _) in addrs {
                                peers_clone.write().await.local_peers.remove(&peer_id);
                            }
                        }
                        SwarmEvent::Behaviour(P2pEvent::Kad(KademliaEvent::RoutingUpdated { peer, .. })) => {
                            tracing::debug!("kademlia routing updated for {}", peer);
                            swarm.behaviour_mut().kademlia.bootstrap().ok();
                        }
                        SwarmEvent::Behaviour(P2pEvent::Autonat(AutonatEvent::StatusChanged { .. })) => {
                            tracing::debug!("autonat status changed");
                        }
                        SwarmEvent::Behaviour(P2pEvent::Relay(RelayEvent::ReservationAccepted { .. })) => {
                            tracing::debug!("relay reservation accepted");
                        }
                        SwarmEvent::Behaviour(P2pEvent::Identify(IdentifyEvent::Received { peer_id, info, .. })) => {
                            tracing::debug!("identify received from {}: {}", peer_id, info.agent_version);
                        }
                        _ => {}
                    }
                }
            }
        }
    });

    tracing::info!("p2p runtime initialized for topic {}", RESEARCH_TOPIC);

    Ok(Arc::new(P2pRuntime {
        sender: cmd_tx,
        peers,
        stats,
    }))
}

/// Get all connected peers
pub async fn get_connected_peers() -> Vec<PeerInfo> {
    let runtime = match RUNTIME.get() {
        Some(r) => r,
        None => return vec![],
    };

    let peers = runtime.peers.read().await;
    peers
        .peers
        .values()
        .filter(|p| p.connected)
        .cloned()
        .collect()
}

/// Get all discovered peers (including disconnected)
pub async fn get_all_peers() -> Vec<PeerInfo> {
    let runtime = match RUNTIME.get() {
        Some(r) => r,
        None => return vec![],
    };

    let peers = runtime.peers.read().await;
    peers.peers.values().cloned().collect()
}

/// Get P2P statistics
pub async fn get_p2p_stats() -> P2pStats {
    let runtime = match RUNTIME.get() {
        Some(r) => r,
        None => return P2pStats::default(),
    };

    runtime.stats.read().await.clone()
}

/// Publish an advisory result to the network
pub async fn publish_advisory_result(body: &str) {
    if !p2p_enabled() {
        return;
    }

    if let Err(e) = ensure_runtime_started().await {
        tracing::warn!("failed to start P2P runtime: {}", e);
        return;
    }

    let Some(runtime) = RUNTIME.get() else {
        return;
    };

    let payload = AdvisoryExperimentResult {
        ts: now_unix(),
        node: current_node_id(),
        topic: RESEARCH_TOPIC,
        advisory: true,
        body: body.to_string(),
    };

    let encoded = match serde_json::to_string(&payload) {
        Ok(v) => v,
        Err(e) => {
            tracing::warn!("failed to serialize payload: {}", e);
            return;
        }
    };

    let _ = runtime
        .sender
        .send(P2pCommand::Publish {
            topic: RESEARCH_TOPIC.to_string(),
            data: encoded.into_bytes(),
        })
        .await;
}

/// Subscribe to a topic
pub async fn subscribe_to_topic(topic: &str) -> Result<()> {
    if !p2p_enabled() {
        return Ok(());
    }

    ensure_runtime_started().await?;

    let Some(runtime) = RUNTIME.get() else {
        return Ok(());
    };

    let _ = runtime
        .sender
        .send(P2pCommand::Subscribe {
            topic: topic.to_string(),
        })
        .await;

    Ok(())
}

/// Parse bootstrap addresses from environment
fn parse_bootstrap_addrs() -> Vec<(PeerId, Multiaddr)> {
    let raw = std::env::var("ZEROCLAW_P2P_BOOTSTRAP").unwrap_or_default();
    parse_bootstrap_addrs_from(&raw)
}

fn parse_bootstrap_addrs_from(raw: &str) -> Vec<(PeerId, Multiaddr)> {
    raw.split(',')
        .filter_map(|entry| {
            let trimmed = entry.trim();
            if trimmed.is_empty() {
                return None;
            }
            let addr: Multiaddr = trimmed.parse().ok()?;
            let peer_id = extract_peer_id(&addr)?;
            Some((peer_id, addr))
        })
        .collect()
}

fn extract_peer_id(addr: &Multiaddr) -> Option<PeerId> {
    addr.iter().find_map(|part| match part {
        Protocol::P2p(multihash) => PeerId::from_multihash(multihash).ok(),
        _ => None,
    })
}

fn p2p_enabled() -> bool {
    std::env::var("ZEROCLAW_P2P_ENABLE")
        .map(|v| v == "1" || v.eq_ignore_ascii_case("true"))
        .unwrap_or(false)
}

fn now_unix() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| d.as_secs())
}

fn current_node_id() -> String {
    std::env::var("ZEROCLAW_NODE_ID")
        .ok()
        .filter(|v| !v.trim().is_empty())
        .unwrap_or_else(|| {
            hostname::get().map_or_else(
                |_| "zeroclaw_node".to_string(),
                |h| h.to_string_lossy().into_owned(),
            )
        })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn advisory_payload_serializes_correctly() {
        let payload = AdvisoryExperimentResult {
            ts: 1,
            node: "zeroclaw_node".to_string(),
            topic: RESEARCH_TOPIC,
            advisory: true,
            body: "test-body".to_string(),
        };

        let json = serde_json::to_value(payload).expect("payload should serialize");
        assert_eq!(json["advisory"], serde_json::json!(true));
        assert_eq!(json["topic"], serde_json::json!(RESEARCH_TOPIC));
    }

    #[test]
    fn bootstrap_addr_without_peer_id_is_ignored() {
        let parsed = parse_bootstrap_addrs_from("/ip4/127.0.0.1/tcp/4001");
        assert!(parsed.is_empty());
    }

    #[test]
    fn p2p_disabled_by_default() {
        // Clear env var if set
        std::env::remove_var("ZEROCLAW_P2P_ENABLE");
        assert!(!p2p_enabled());
    }

    #[test]
    fn p2p_enabled_with_env_var() {
        std::env::set_var("ZEROCLAW_P2P_ENABLE", "1");
        assert!(p2p_enabled());

        std::env::set_var("ZEROCLAW_P2P_ENABLE", "true");
        assert!(p2p_enabled());

        std::env::set_var("ZEROCLAW_P2P_ENABLE", "TRUE");
        assert!(p2p_enabled());

        std::env::set_var("ZEROCLAW_P2P_ENABLE", "false");
        assert!(!p2p_enabled());
    }

    #[test]
    fn peer_info_serializes() {
        let info = PeerInfo {
            peer_id: "QmTest".to_string(),
            addresses: vec!["/ip4/127.0.0.1/tcp/4001".to_string()],
            connected: true,
            last_ping: Some(1000),
            last_pong: Some(1005),
            latency_ms: Some(5),
            discovered_via: "mdns".to_string(),
            first_seen: 1000,
        };

        let json = serde_json::to_value(&info).expect("PeerInfo should serialize");
        assert_eq!(json["connected"], serde_json::json!(true));
        assert_eq!(json["latency_ms"], serde_json::json!(5));
    }

    #[test]
    fn stats_default_values() {
        let stats = P2pStats::default();
        assert_eq!(stats.messages_published, 0);
        assert_eq!(stats.messages_received, 0);
        assert_eq!(stats.peers_connected, 0);
    }
}
