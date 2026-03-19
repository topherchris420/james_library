//! libp2p runtime: gossipsub pub/sub + Kademlia DHT.
//!
//! This module is only compiled when the `p2p` feature is enabled.

use anyhow::{Context, Result};
use futures_util::StreamExt;
use libp2p::{
    gossipsub::{self, IdentTopic, MessageAuthenticity},
    identify, identity,
    kad::{self, store::MemoryStore, Record, RecordKey},
    multiaddr::Protocol,
    noise,
    swarm::{NetworkBehaviour, SwarmEvent},
    tcp, yamux, Multiaddr, PeerId, SwarmBuilder,
};
use tokio::sync::{mpsc, oneshot};

use std::collections::{HashMap, HashSet};

use super::{
    now_unix, p2p_enabled, sanitize_for_advisory, AdvisoryExperimentResult, P2pRuntimeConfig,
    P2pStatus, DEFAULT_ADVISORY_TOPIC,
};

// ── Swarm behaviour ────────────────────────────────────────────────

#[derive(NetworkBehaviour)]
struct P2pBehaviour {
    gossipsub: gossipsub::Behaviour,
    kademlia: kad::Behaviour<MemoryStore>,
    identify: identify::Behaviour,
}

// ── Commands sent to the swarm task ────────────────────────────────

enum SwarmCommand {
    /// Publish raw bytes to a gossipsub topic.
    Publish { topic: String, data: Vec<u8> },
    /// Store a key-value record in the Kademlia DHT.
    PutRecord {
        key: Vec<u8>,
        value: Vec<u8>,
        reply: oneshot::Sender<Result<()>>,
    },
    /// Retrieve a record from the Kademlia DHT.
    GetRecord {
        key: Vec<u8>,
        reply: oneshot::Sender<Result<Option<Vec<u8>>>>,
    },
    /// Query current node status.
    Status { reply: oneshot::Sender<P2pStatus> },
}

// ── Singleton state ────────────────────────────────────────────────

struct P2pHandle {
    cmd_tx: mpsc::Sender<SwarmCommand>,
    node_id: String,
    subscribed_topics: Vec<String>,
}

static HANDLE: tokio::sync::OnceCell<P2pHandle> = tokio::sync::OnceCell::const_new();

// ── Public API ─────────────────────────────────────────────────────

/// Initialize the P2P runtime if enabled. Idempotent — safe to call multiple times.
pub async fn ensure_runtime_started(cfg: &crate::config::schema::P2pConfig) -> Result<()> {
    if !p2p_enabled(cfg) {
        return Ok(());
    }

    let rt_cfg = P2pRuntimeConfig::from_config(cfg);

    HANDLE
        .get_or_try_init(|| init_runtime(rt_cfg))
        .await
        .map(|_| ())
}

/// Publish a sanitized advisory message to the default advisory topic.
pub async fn publish_advisory_result(cfg: &crate::config::schema::P2pConfig, body: &str) {
    if !p2p_enabled(cfg) {
        return;
    }

    let Some(handle) = HANDLE.get() else {
        return;
    };

    let Some(sanitized) = sanitize_for_advisory(body) else {
        return;
    };

    let payload = AdvisoryExperimentResult {
        ts: now_unix(),
        node: handle.node_id.clone(),
        topic: DEFAULT_ADVISORY_TOPIC.to_string(),
        advisory: true,
        body: sanitized,
    };

    let encoded = match serde_json::to_string(&payload) {
        Ok(v) => v,
        Err(_) => return,
    };

    let _ = handle
        .cmd_tx
        .send(SwarmCommand::Publish {
            topic: DEFAULT_ADVISORY_TOPIC.to_string(),
            data: encoded.into_bytes(),
        })
        .await;
}

/// Publish raw data to a specific gossipsub topic.
pub async fn publish_to_topic(
    cfg: &crate::config::schema::P2pConfig,
    topic: &str,
    data: &[u8],
) -> Result<()> {
    if !p2p_enabled(cfg) {
        anyhow::bail!("p2p is not enabled");
    }

    let handle = HANDLE.get().context("p2p runtime not started")?;

    handle
        .cmd_tx
        .send(SwarmCommand::Publish {
            topic: topic.to_string(),
            data: data.to_vec(),
        })
        .await
        .context("p2p runtime channel closed")?;

    Ok(())
}

/// Store a key-value pair in the Kademlia DHT.
pub async fn put_dht_record(
    cfg: &crate::config::schema::P2pConfig,
    key: &[u8],
    value: &[u8],
) -> Result<()> {
    if !p2p_enabled(cfg) {
        anyhow::bail!("p2p is not enabled");
    }

    let handle = HANDLE.get().context("p2p runtime not started")?;
    let (tx, rx) = oneshot::channel();

    handle
        .cmd_tx
        .send(SwarmCommand::PutRecord {
            key: key.to_vec(),
            value: value.to_vec(),
            reply: tx,
        })
        .await
        .context("p2p runtime channel closed")?;

    rx.await.context("p2p runtime dropped reply")?
}

/// Retrieve a value from the Kademlia DHT by key.
pub async fn get_dht_record(
    cfg: &crate::config::schema::P2pConfig,
    key: &[u8],
) -> Result<Option<Vec<u8>>> {
    if !p2p_enabled(cfg) {
        anyhow::bail!("p2p is not enabled");
    }

    let handle = HANDLE.get().context("p2p runtime not started")?;
    let (tx, rx) = oneshot::channel();

    handle
        .cmd_tx
        .send(SwarmCommand::GetRecord {
            key: key.to_vec(),
            reply: tx,
        })
        .await
        .context("p2p runtime channel closed")?;

    rx.await.context("p2p runtime dropped reply")?
}

/// Get current P2P node status.
pub fn get_status(cfg: &crate::config::schema::P2pConfig) -> P2pStatus {
    let enabled = p2p_enabled(cfg);

    let Some(handle) = HANDLE.get() else {
        return P2pStatus {
            enabled,
            running: false,
            local_peer_id: None,
            listen_addresses: Vec::new(),
            connected_peers: 0,
            subscribed_topics: handle_topics_or_default(None),
        };
    };

    // Try synchronous status query with a short timeout
    let (tx, rx) = oneshot::channel();
    if handle
        .cmd_tx
        .try_send(SwarmCommand::Status { reply: tx })
        .is_err()
    {
        return P2pStatus {
            enabled,
            running: true,
            local_peer_id: None,
            listen_addresses: Vec::new(),
            connected_peers: 0,
            subscribed_topics: handle.subscribed_topics.clone(),
        };
    }

    // Block briefly for the reply — this runs in an async context so it's fine
    match rx.blocking_recv() {
        Ok(status) => status,
        Err(_) => P2pStatus {
            enabled,
            running: true,
            local_peer_id: None,
            listen_addresses: Vec::new(),
            connected_peers: 0,
            subscribed_topics: handle.subscribed_topics.clone(),
        },
    }
}

fn handle_topics_or_default(topics: Option<&[String]>) -> Vec<String> {
    topics
        .map(|t| t.to_vec())
        .unwrap_or_else(|| vec![DEFAULT_ADVISORY_TOPIC.to_string()])
}

// ── Runtime initialization ─────────────────────────────────────────

async fn init_runtime(rt_cfg: P2pRuntimeConfig) -> Result<P2pHandle> {
    let listen_addr: Multiaddr = rt_cfg
        .listen_addr
        .parse()
        .context("invalid p2p listen address")?;

    let key = identity::Keypair::generate_ed25519();
    let local_peer_id = PeerId::from(key.public());

    // Build gossipsub
    let gossip_cfg = gossipsub::ConfigBuilder::default()
        .validation_mode(gossipsub::ValidationMode::Strict)
        .max_transmit_size(rt_cfg.max_message_size)
        .build()
        .context("failed to build gossipsub config")?;

    let mut gossipsub_behaviour =
        gossipsub::Behaviour::new(MessageAuthenticity::Signed(key.clone()), gossip_cfg)
            .map_err(|e| anyhow::anyhow!("failed to construct gossipsub: {e}"))?;

    // Subscribe to configured topics
    let mut subscribed_topics = Vec::new();
    for topic_str in &rt_cfg.topics {
        let topic = IdentTopic::new(topic_str);
        gossipsub_behaviour
            .subscribe(&topic)
            .context(format!("failed to subscribe to topic: {topic_str}"))?;
        subscribed_topics.push(topic_str.clone());
    }

    // Build Kademlia
    let store = MemoryStore::new(local_peer_id);
    let kademlia = kad::Behaviour::new(local_peer_id, store);

    // Build identify (helps peers exchange listen addresses)
    let identify_behaviour = identify::Behaviour::new(identify::Config::new(
        "/zeroclaw/0.1.0".to_string(),
        key.public(),
    ));

    // Build swarm
    let mut swarm = SwarmBuilder::with_existing_identity(key)
        .with_tokio()
        .with_tcp(
            tcp::Config::default(),
            noise::Config::new,
            yamux::Config::default,
        )
        .context("failed to build tcp transport")?
        .with_behaviour(|_| P2pBehaviour {
            gossipsub: gossipsub_behaviour,
            kademlia,
            identify: identify_behaviour,
        })
        .context("failed to build p2p behaviour")?
        .build();

    swarm
        .listen_on(listen_addr)
        .context("failed to bind p2p listen address")?;

    // Add bootstrap peers to Kademlia routing table
    for addr_str in &rt_cfg.bootstrap_peers {
        if let Ok(addr) = addr_str.parse::<Multiaddr>() {
            if let Some(peer_id) = extract_peer_id(&addr) {
                swarm.behaviour_mut().kademlia.add_address(&peer_id, addr);
            }
        }
    }

    // Kick off Kademlia bootstrap if we have bootstrap peers
    if !rt_cfg.bootstrap_peers.is_empty() {
        if let Err(e) = swarm.behaviour_mut().kademlia.bootstrap() {
            tracing::warn!("kademlia bootstrap failed: {e}");
        }
    }

    let (cmd_tx, cmd_rx) = mpsc::channel::<SwarmCommand>(256);
    let topics_clone = subscribed_topics.clone();
    let node_id = rt_cfg.node_id.clone();

    // Spawn the swarm event loop
    tokio::spawn(swarm_loop(
        swarm,
        cmd_rx,
        local_peer_id,
        topics_clone.clone(),
    ));

    tracing::info!(
        peer_id = %local_peer_id,
        topics = ?topics_clone,
        "p2p runtime initialized"
    );

    Ok(P2pHandle {
        cmd_tx,
        node_id,
        subscribed_topics,
    })
}

fn extract_peer_id(addr: &Multiaddr) -> Option<PeerId> {
    addr.iter().find_map(|part| match part {
        Protocol::P2p(peer_id) => Some(peer_id),
        _ => None,
    })
}

// ── Swarm event loop ───────────────────────────────────────────────

async fn swarm_loop(
    mut swarm: libp2p::Swarm<P2pBehaviour>,
    mut cmd_rx: mpsc::Receiver<SwarmCommand>,
    local_peer_id: PeerId,
    subscribed_topics: Vec<String>,
) {
    // Track pending DHT get queries
    let mut pending_get_queries: HashMap<kad::QueryId, oneshot::Sender<Result<Option<Vec<u8>>>>> =
        HashMap::new();
    let mut pending_put_queries: HashMap<kad::QueryId, oneshot::Sender<Result<()>>> =
        HashMap::new();
    let mut listen_addresses: Vec<String> = Vec::new();
    let mut connected_peers: HashSet<PeerId> = HashSet::new();

    loop {
        tokio::select! {
            cmd = cmd_rx.recv() => {
                match cmd {
                    Some(SwarmCommand::Publish { topic, data }) => {
                        let ident_topic = IdentTopic::new(&topic);
                        if let Err(err) = swarm.behaviour_mut().gossipsub.publish(ident_topic, data) {
                            tracing::warn!("p2p gossip publish to {topic} failed: {err}");
                        }
                    }
                    Some(SwarmCommand::PutRecord { key, value, reply }) => {
                        let record = Record {
                            key: RecordKey::new(&key),
                            value,
                            publisher: None,
                            expires: None,
                        };
                        match swarm.behaviour_mut().kademlia.put_record(record, kad::Quorum::One) {
                            Ok(query_id) => {
                                pending_put_queries.insert(query_id, reply);
                            }
                            Err(e) => {
                                let _ = reply.send(Err(anyhow::anyhow!("kademlia put failed: {e}")));
                            }
                        }
                    }
                    Some(SwarmCommand::GetRecord { key, reply }) => {
                        let query_id = swarm.behaviour_mut().kademlia.get_record(RecordKey::new(&key));
                        pending_get_queries.insert(query_id, reply);
                    }
                    Some(SwarmCommand::Status { reply }) => {
                        let status = P2pStatus {
                            enabled: true,
                            running: true,
                            local_peer_id: Some(local_peer_id.to_string()),
                            listen_addresses: listen_addresses.clone(),
                            connected_peers: connected_peers.len(),
                            subscribed_topics: subscribed_topics.clone(),
                        };
                        let _ = reply.send(status);
                    }
                    None => break,
                }
            }
            event = swarm.select_next_some() => {
                match event {
                    SwarmEvent::NewListenAddr { address, .. } => {
                        let addr_str = address.to_string();
                        tracing::info!("p2p listening on {addr_str}");
                        listen_addresses.push(addr_str);
                    }
                    SwarmEvent::ConnectionEstablished { peer_id, .. } => {
                        connected_peers.insert(peer_id);
                        tracing::debug!("p2p peer connected: {peer_id}");
                    }
                    SwarmEvent::ConnectionClosed { peer_id, .. } => {
                        connected_peers.remove(&peer_id);
                        tracing::debug!("p2p peer disconnected: {peer_id}");
                    }

                    // Gossipsub events
                    SwarmEvent::Behaviour(P2pBehaviourEvent::Gossipsub(
                        gossipsub::Event::Message { message, .. },
                    )) => {
                        let source = message
                            .source
                            .map_or_else(|| "unknown".to_string(), |p| p.to_string());
                        let topic = message.topic.to_string();
                        tracing::debug!(
                            from = %source,
                            topic = %topic,
                            bytes = message.data.len(),
                            "p2p gossip message received"
                        );
                    }

                    // Kademlia events
                    SwarmEvent::Behaviour(P2pBehaviourEvent::Kademlia(
                        kad::Event::OutboundQueryProgressed { id, result, .. },
                    )) => {
                        match result {
                            kad::QueryResult::GetRecord(Ok(
                                kad::GetRecordOk::FoundRecord(kad::PeerRecord { record, .. }),
                            )) => {
                                if let Some(reply) = pending_get_queries.remove(&id) {
                                    let _ = reply.send(Ok(Some(record.value)));
                                }
                            }
                            kad::QueryResult::GetRecord(Ok(
                                kad::GetRecordOk::FinishedWithNoAdditionalRecord { .. },
                            )) => {
                                // Only reply if we haven't already (from FoundRecord)
                                if let Some(reply) = pending_get_queries.remove(&id) {
                                    let _ = reply.send(Ok(None));
                                }
                            }
                            kad::QueryResult::GetRecord(Err(e)) => {
                                if let Some(reply) = pending_get_queries.remove(&id) {
                                    let _ = reply.send(Err(anyhow::anyhow!(
                                        "kademlia get failed: {e:?}"
                                    )));
                                }
                            }
                            kad::QueryResult::PutRecord(Ok(_)) => {
                                if let Some(reply) = pending_put_queries.remove(&id) {
                                    let _ = reply.send(Ok(()));
                                }
                            }
                            kad::QueryResult::PutRecord(Err(e)) => {
                                if let Some(reply) = pending_put_queries.remove(&id) {
                                    let _ = reply.send(Err(anyhow::anyhow!(
                                        "kademlia put failed: {e:?}"
                                    )));
                                }
                            }
                            kad::QueryResult::Bootstrap(Ok(_)) => {
                                tracing::info!("kademlia bootstrap completed");
                            }
                            kad::QueryResult::Bootstrap(Err(e)) => {
                                tracing::warn!("kademlia bootstrap error: {e:?}");
                            }
                            _ => {}
                        }
                    }
                    SwarmEvent::Behaviour(P2pBehaviourEvent::Kademlia(
                        kad::Event::RoutingUpdated { peer, .. },
                    )) => {
                        tracing::debug!("kademlia routing updated for peer: {peer}");
                    }

                    // Identify events — add discovered addresses to Kademlia
                    SwarmEvent::Behaviour(P2pBehaviourEvent::Identify(
                        identify::Event::Received { peer_id, info, .. },
                    )) => {
                        for addr in &info.listen_addrs {
                            swarm
                                .behaviour_mut()
                                .kademlia
                                .add_address(&peer_id, addr.clone());
                        }
                        tracing::debug!(
                            peer = %peer_id,
                            addrs = info.listen_addrs.len(),
                            "identify: discovered peer addresses"
                        );
                    }

                    _ => {}
                }
            }
        }
    }
}
