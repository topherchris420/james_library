use serde::Serialize;

use std::time::{SystemTime, UNIX_EPOCH};

pub const DEFAULT_ADVISORY_TOPIC: &str = "zeroclaw/advisory";
const DEFAULT_LISTEN_ADDR: &str = "/ip4/127.0.0.1/tcp/0";
const MAX_ADVISORY_PAYLOAD: usize = 512;

/// Serialized payload published to gossip topics.
#[derive(Debug, Clone, Serialize)]
pub struct AdvisoryExperimentResult {
    pub ts: u64,
    pub node: String,
    pub topic: String,
    pub advisory: bool,
    pub body: String,
}

/// Summary of a connected peer.
#[derive(Debug, Clone, Serialize)]
pub struct PeerInfo {
    pub peer_id: String,
    pub addresses: Vec<String>,
}

/// Snapshot of the running P2P node status.
#[derive(Debug, Clone, Serialize)]
pub struct P2pStatus {
    pub enabled: bool,
    pub running: bool,
    pub local_peer_id: Option<String>,
    pub listen_addresses: Vec<String>,
    pub connected_peers: usize,
    pub subscribed_topics: Vec<String>,
}

/// Resolved P2P runtime configuration merging config file + env overrides.
#[derive(Debug, Clone)]
pub struct P2pRuntimeConfig {
    pub listen_addr: String,
    pub bootstrap_peers: Vec<String>,
    pub topics: Vec<String>,
    pub max_message_size: usize,
    pub max_peers: usize,
    pub node_id: String,
}

impl P2pRuntimeConfig {
    /// Build from config schema, applying env-var overrides.
    pub fn from_config(cfg: &crate::config::schema::P2pConfig) -> Self {
        let listen_addr = std::env::var("ZEROCLAW_P2P_LISTEN_ADDR")
            .ok()
            .filter(|v| !v.trim().is_empty())
            .unwrap_or_else(|| {
                if cfg.listen_addr.is_empty() {
                    DEFAULT_LISTEN_ADDR.to_string()
                } else {
                    cfg.listen_addr.clone()
                }
            });

        let bootstrap_peers = std::env::var("ZEROCLAW_P2P_BOOTSTRAP")
            .ok()
            .filter(|v| !v.trim().is_empty())
            .map(|raw| {
                raw.split(',')
                    .map(|s| s.trim().to_string())
                    .filter(|s| !s.is_empty())
                    .collect()
            })
            .unwrap_or_else(|| cfg.bootstrap_peers.clone());

        let mut topics = cfg.topics.clone();
        if topics.is_empty() {
            topics.push(DEFAULT_ADVISORY_TOPIC.to_string());
        }

        let node_id = std::env::var("ZEROCLAW_NODE_ID")
            .ok()
            .filter(|v| !v.trim().is_empty())
            .or_else(|| cfg.node_id.clone())
            .unwrap_or_else(|| {
                hostname::get().map_or_else(
                    |_| "zeroclaw_node".to_string(),
                    |h| h.to_string_lossy().into_owned(),
                )
            });

        Self {
            listen_addr,
            bootstrap_peers,
            topics,
            max_message_size: cfg.max_message_size,
            max_peers: cfg.max_peers,
            node_id,
        }
    }
}

/// Check whether P2P is enabled (config or env).
pub fn p2p_enabled(cfg: &crate::config::schema::P2pConfig) -> bool {
    if cfg.enabled {
        return true;
    }
    std::env::var("ZEROCLAW_P2P_ENABLE")
        .map(|v| v == "1" || v.eq_ignore_ascii_case("true"))
        .unwrap_or(false)
}

// ── libp2p runtime (only compiled with p2p feature) ────────────────

#[cfg(feature = "p2p")]
mod runtime;

#[cfg(feature = "p2p")]
pub use runtime::{
    ensure_runtime_started, get_dht_record, get_status, publish_advisory_result, publish_to_topic,
    put_dht_record,
};

// ── Stubs when p2p feature is disabled ─────────────────────────────

#[cfg(not(feature = "p2p"))]
#[allow(clippy::unused_async)]
pub async fn ensure_runtime_started(_cfg: &crate::config::schema::P2pConfig) -> anyhow::Result<()> {
    Ok(())
}

#[cfg(not(feature = "p2p"))]
#[allow(clippy::unused_async)]
pub async fn publish_advisory_result(_cfg: &crate::config::schema::P2pConfig, _body: &str) {}

#[cfg(not(feature = "p2p"))]
#[allow(clippy::unused_async)]
pub async fn publish_to_topic(
    _cfg: &crate::config::schema::P2pConfig,
    _topic: &str,
    _data: &[u8],
) -> anyhow::Result<()> {
    anyhow::bail!("p2p feature not enabled at compile time");
}

#[cfg(not(feature = "p2p"))]
#[allow(clippy::unused_async)]
pub async fn put_dht_record(
    _cfg: &crate::config::schema::P2pConfig,
    _key: &[u8],
    _value: &[u8],
) -> anyhow::Result<()> {
    anyhow::bail!("p2p feature not enabled at compile time");
}

#[cfg(not(feature = "p2p"))]
#[allow(clippy::unused_async)]
pub async fn get_dht_record(
    _cfg: &crate::config::schema::P2pConfig,
    _key: &[u8],
) -> anyhow::Result<Option<Vec<u8>>> {
    anyhow::bail!("p2p feature not enabled at compile time");
}

#[cfg(not(feature = "p2p"))]
pub fn get_status(_cfg: &crate::config::schema::P2pConfig) -> P2pStatus {
    P2pStatus {
        enabled: false,
        running: false,
        local_peer_id: None,
        listen_addresses: Vec::new(),
        connected_peers: 0,
        subscribed_topics: Vec::new(),
    }
}

// ── Shared helpers ──────────────────────────────────────────────────

pub(crate) fn now_unix() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| d.as_secs())
}

/// Parse comma-separated multiaddr bootstrap list into (peer_id, addr) pairs.
pub fn parse_bootstrap_addrs_from(raw: &str) -> Vec<(String, String)> {
    raw.split(',')
        .filter_map(|entry| {
            let trimmed = entry.trim();
            if trimmed.is_empty() {
                return None;
            }
            // Validate it contains /p2p/ component
            if !trimmed.contains("/p2p/") {
                tracing::warn!("bootstrap addr missing /p2p/ peer ID component: {trimmed}");
                return None;
            }
            // Extract peer ID from the /p2p/<id> suffix
            let peer_id = trimmed.rsplit("/p2p/").next().map(|s| s.to_string())?;
            if peer_id.is_empty() {
                return None;
            }
            Some((peer_id, trimmed.to_string()))
        })
        .collect()
}

/// Sanitize a response string for safe P2P broadcast.
/// Returns None if the content contains sensitive keywords or is empty.
pub fn sanitize_for_advisory(response: &str) -> Option<String> {
    let lower = response.to_ascii_lowercase();
    let blocked = [
        "api_key",
        "token",
        "password",
        "secret",
        "bearer",
        "credential",
    ];
    if blocked.iter().any(|k| lower.contains(k)) {
        return None;
    }

    let trimmed = response.trim();
    if trimmed.is_empty() {
        return None;
    }

    let mut out = String::new();
    for ch in trimmed.chars().take(MAX_ADVISORY_PAYLOAD) {
        out.push(ch);
    }
    Some(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn advisory_payload_marks_advisory() {
        let payload = AdvisoryExperimentResult {
            ts: 1,
            node: "zeroclaw_node".to_string(),
            topic: DEFAULT_ADVISORY_TOPIC.to_string(),
            advisory: true,
            body: "test-body".to_string(),
        };

        let json = serde_json::to_value(payload).expect("payload should serialize");
        assert_eq!(json["advisory"], serde_json::json!(true));
        assert_eq!(json["topic"], serde_json::json!(DEFAULT_ADVISORY_TOPIC));
    }

    #[test]
    fn bootstrap_addr_without_peer_id_is_ignored() {
        let parsed = parse_bootstrap_addrs_from("/ip4/127.0.0.1/tcp/4001");
        assert!(parsed.is_empty());
    }

    #[test]
    fn bootstrap_addr_with_peer_id_is_parsed() {
        let input = "/ip4/10.0.0.1/tcp/4001/p2p/12D3KooWTestPeerId";
        let parsed = parse_bootstrap_addrs_from(input);
        assert_eq!(parsed.len(), 1);
        assert_eq!(parsed[0].0, "12D3KooWTestPeerId");
        assert_eq!(parsed[0].1, input);
    }

    #[test]
    fn bootstrap_multiple_addrs_parsed() {
        let input = "/ip4/10.0.0.1/tcp/4001/p2p/PeerA, /ip4/10.0.0.2/tcp/4001/p2p/PeerB";
        let parsed = parse_bootstrap_addrs_from(input);
        assert_eq!(parsed.len(), 2);
    }

    #[test]
    fn sanitize_blocks_sensitive_keywords() {
        assert!(sanitize_for_advisory("token=abcd").is_none());
        assert!(sanitize_for_advisory("my api_key is here").is_none());
        assert!(sanitize_for_advisory("bearer xyz").is_none());
    }

    #[test]
    fn sanitize_limits_output_size() {
        let input = "x".repeat(600);
        let output = sanitize_for_advisory(&input).expect("sanitized output expected");
        assert_eq!(output.len(), MAX_ADVISORY_PAYLOAD);
    }

    #[test]
    fn sanitize_blocks_empty_input() {
        assert!(sanitize_for_advisory("").is_none());
        assert!(sanitize_for_advisory("   ").is_none());
    }

    #[test]
    fn sanitize_passes_clean_input() {
        let output = sanitize_for_advisory("research result: 42Hz resonance detected");
        assert!(output.is_some());
    }

    #[test]
    fn runtime_config_defaults_apply() {
        let cfg = crate::config::schema::P2pConfig::default();
        let rt = P2pRuntimeConfig::from_config(&cfg);
        assert_eq!(rt.listen_addr, DEFAULT_LISTEN_ADDR);
        assert_eq!(rt.topics, vec![DEFAULT_ADVISORY_TOPIC]);
        assert_eq!(rt.max_message_size, 1024);
        assert_eq!(rt.max_peers, 50);
    }

    #[test]
    fn p2p_disabled_by_default() {
        let cfg = crate::config::schema::P2pConfig::default();
        // Without env var set, should be disabled
        assert!(!cfg.enabled);
    }
}
