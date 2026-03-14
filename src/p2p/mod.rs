use anyhow::{Context, Result};
use futures_util::StreamExt;
use libp2p::{
    gossipsub::{self, IdentTopic, MessageAuthenticity},
    identity,
    kad::{store::MemoryStore, Behaviour as Kademlia, Event as KademliaEvent},
    multiaddr::Protocol,
    noise,
    swarm::{NetworkBehaviour, SwarmEvent},
    tcp, yamux, Multiaddr, PeerId, SwarmBuilder,
};
use serde::Serialize;

use std::time::{SystemTime, UNIX_EPOCH};
use tokio::sync::mpsc;

pub const RESEARCH_TOPIC: &str = "research/acoustic-physics";
const DEFAULT_LISTEN_ADDR: &str = "/ip4/127.0.0.1/tcp/0";

static PUBLISHER: tokio::sync::OnceCell<mpsc::Sender<String>> = tokio::sync::OnceCell::const_new();

#[derive(Debug, Clone, Serialize)]
pub struct AdvisoryExperimentResult {
    pub ts: u64,
    pub node: String,
    pub topic: &'static str,
    pub advisory: bool,
    pub body: String,
}

#[derive(NetworkBehaviour)]
#[behaviour(to_swarm = "P2pEvent")]
struct P2pBehaviour {
    gossipsub: gossipsub::Behaviour,
    kademlia: Kademlia<MemoryStore>,
}

#[derive(Debug)]
enum P2pEvent {
    Gossip(gossipsub::Event),
    Kad(KademliaEvent),
}

impl From<gossipsub::Event> for P2pEvent {
    fn from(value: gossipsub::Event) -> Self {
        Self::Gossip(value)
    }
}

impl From<KademliaEvent> for P2pEvent {
    fn from(value: KademliaEvent) -> Self {
        Self::Kad(value)
    }
}

pub async fn ensure_runtime_started() -> Result<()> {
    if !p2p_enabled() {
        return Ok(());
    }

    let _ = PUBLISHER.get_or_try_init(init_runtime).await?;
    Ok(())
}

async fn init_runtime() -> Result<mpsc::Sender<String>> {
    let listen_addr: Multiaddr = std::env::var("ZEROCLAW_P2P_LISTEN_ADDR")
        .unwrap_or_else(|_| DEFAULT_LISTEN_ADDR.to_string())
        .parse()
        .context("invalid ZEROCLAW_P2P_LISTEN_ADDR")?;

    let key = identity::Keypair::generate_ed25519();
    let local_peer_id = PeerId::from(key.public());

    let topic = IdentTopic::new(RESEARCH_TOPIC);
    let gossip_cfg = gossipsub::ConfigBuilder::default()
        .validation_mode(gossipsub::ValidationMode::Strict)
        .build()
        .context("failed to build gossipsub config")?;

    let mut gossipsub =
        gossipsub::Behaviour::new(MessageAuthenticity::Signed(key.clone()), gossip_cfg)
            .context("failed to construct gossipsub")?;
    gossipsub
        .subscribe(&topic)
        .context("failed to subscribe to research topic")?;

    let store = MemoryStore::new(local_peer_id);
    let kademlia = Kademlia::new(local_peer_id, store);

    let mut swarm = SwarmBuilder::with_existing_identity(key)
        .with_tokio()
        .with_tcp(
            tcp::Config::default(),
            noise::Config::new,
            yamux::Config::default,
        )
        .context("failed to build tcp transport")?
        .with_behaviour(|_| P2pBehaviour {
            gossipsub,
            kademlia,
        })
        .context("failed to build p2p behaviour")?
        .build();

    swarm
        .listen_on(listen_addr)
        .context("failed to bind p2p listen address")?;

    let bootstrap_addrs = parse_bootstrap_addrs();
    for (peer_id, addr) in bootstrap_addrs {
        swarm.behaviour_mut().kademlia.add_address(&peer_id, addr);
    }

    let (tx, mut rx) = mpsc::channel::<String>(128);
    let topic_for_task = topic.clone();

    tokio::spawn(async move {
        loop {
            tokio::select! {
                msg = rx.recv() => {
                    match msg {
                        Some(body) => {
                            if let Err(err) = swarm.behaviour_mut().gossipsub.publish(topic_for_task.clone(), body.as_bytes()) {
                                tracing::warn!("p2p publish failed: {err}");
                            }
                        }
                        None => break,
                    }
                }
                event = swarm.select_next_some() => {
                    match event {
                        SwarmEvent::NewListenAddr { address, .. } => {
                            tracing::info!("p2p listening on {address}");
                        }
                        SwarmEvent::Behaviour(P2pEvent::Gossip(gossipsub::Event::Message { message, .. })) => {
                            let source = message.source.map_or_else(|| "unknown".to_string(), |p| p.to_string());
                            tracing::debug!("p2p gossip message from {source} on {}", RESEARCH_TOPIC);
                        }
                        SwarmEvent::Behaviour(P2pEvent::Kad(_)) => {}
                        _ => {}
                    }
                }
            }
        }
    });

    tracing::info!("p2p runtime initialized for topic {RESEARCH_TOPIC}");
    Ok(tx)
}

pub async fn publish_advisory_result(body: &str) {
    if !p2p_enabled() {
        return;
    }

    if ensure_runtime_started().await.is_err() {
        return;
    }

    let Some(tx) = PUBLISHER.get() else {
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
        Err(_) => return,
    };

    let _ = tx.send(encoded).await;
}

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
    fn advisory_payload_marks_advisory() {
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
}
