//! Hardware, storage, and network capabilities plus the node's privacy
//! posture: which listeners are exposed and which external services the
//! configuration would contact.
//!
//! The Rig itself opens no listeners. The only R.A.I.N.-owned listener it
//! reports is the gateway/daemon, whose bind policy stays in `gateway`.

use super::capability::{CapabilityState, CapabilityStatus};
use super::context::{RigContext, selected_provider};
use super::research::{MeetingInference, jev_enabled};
use crate::config::{RigPrivacyMode, RigPrivacySource};
use crate::providers::locality::{
    EndpointLocality, classify_host_resolved, resolve_inference_target, system_resolve,
};
use serde::Serialize;

/// How widely a listener is reachable.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BindExposure {
    Loopback,
    PrivateNetwork,
    /// `0.0.0.0` / `::` — every interface, including public ones.
    AllInterfaces,
    Public,
}

impl BindExposure {
    pub fn classify(host: &str) -> Self {
        let bare = host.trim().trim_start_matches('[').trim_end_matches(']');
        if matches!(bare, "0.0.0.0" | "::" | "0:0:0:0:0:0:0:0") {
            return Self::AllInterfaces;
        }
        match classify_host_resolved(bare, system_resolve) {
            EndpointLocality::Loopback => Self::Loopback,
            EndpointLocality::PrivateNetwork => Self::PrivateNetwork,
            EndpointLocality::Remote => Self::Public,
        }
    }

    pub fn is_loopback(self) -> bool {
        self == Self::Loopback
    }

    pub fn label(self) -> &'static str {
        match self {
            Self::Loopback => "loopback only",
            Self::PrivateNetwork => "local network",
            Self::AllInterfaces => "ALL INTERFACES",
            Self::Public => "PUBLIC",
        }
    }
}

/// A network listener R.A.I.N. would open.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ListenerStatus {
    pub component: String,
    pub host: String,
    pub port: u16,
    pub exposure: BindExposure,
    /// Non-loopback bind explicitly allowed (`allow_public_bind` or a tunnel).
    pub explicitly_allowed: bool,
    /// Publicly reachable through a configured tunnel provider.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tunnel: Option<String>,
}

/// A service outside this machine/LAN that the configuration would contact.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ExternalService {
    /// `inference`, `judgment`, `meeting`, `channel`, or `tunnel`.
    pub kind: String,
    pub name: String,
    /// Whether the Rust runtime refuses it under `privacy = "local"`.
    pub refused_in_local_mode: bool,
}

/// Privacy posture of the node.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct PrivacyStatus {
    pub mode: RigPrivacyMode,
    pub source: RigPrivacySource,
    /// Provider construction refuses non-local inference.
    pub local_inference_enforced: bool,
    pub external_services: Vec<ExternalService>,
    /// Configured services that contradict `privacy = "local"`.
    pub violations: Vec<String>,
}

/// Listeners and external services.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct NetworkStatus {
    pub listeners: Vec<ListenerStatus>,
    /// Listeners that are not loopback-only.
    pub exposed_listeners: usize,
    pub external_services: usize,
}

/// Every configured inference provider id (primary, fallbacks, routes, delegates).
fn configured_inference_providers(ctx: &RigContext) -> Vec<(String, &'static str, Option<String>)> {
    let config = &ctx.config;
    let mut providers = vec![(
        selected_provider(config),
        "default provider",
        config.api_url.clone(),
    )];
    for fallback in &config.reliability.fallback_providers {
        let name = if fallback.starts_with("custom:") || fallback.starts_with("anthropic-custom:") {
            fallback.clone()
        } else {
            fallback.split(':').next().unwrap_or(fallback).to_string()
        };
        providers.push((name, "fallback provider", None));
    }
    for route in &config.model_routes {
        providers.push((route.provider.clone(), "model route", None));
    }
    let mut delegates: Vec<_> = config
        .agents
        .values()
        .map(|agent| agent.provider.clone())
        .collect();
    delegates.sort();
    for provider in delegates {
        providers.push((provider, "delegate agent", None));
    }
    providers
}

/// Assess privacy mode against everything the configuration would contact.
pub fn assess_privacy(ctx: &RigContext) -> PrivacyStatus {
    let (mode, source) = ctx.config.rig.effective_privacy();
    let local_mode = mode == RigPrivacyMode::Local;
    let mut external = Vec::new();
    let mut violations = Vec::new();

    let mut seen = std::collections::BTreeSet::new();
    for (provider, role, api_url) in configured_inference_providers(ctx) {
        let target = resolve_inference_target(&provider, api_url.as_deref());
        if target.locality.is_local() || !seen.insert(provider.clone()) {
            continue;
        }
        let provider = crate::providers::locality::display_provider_id(&provider);
        external.push(ExternalService {
            kind: "inference".into(),
            name: format!("{provider} ({role})"),
            refused_in_local_mode: true,
        });
        if local_mode {
            violations.push(format!(
                "{role} '{provider}' is hosted; the runtime will refuse it in local privacy mode"
            ));
        }
    }

    let meeting = MeetingInference::from_context(ctx);
    if meeting.is_hosted() {
        let what = if meeting.hosted_model {
            format!(
                "R.A.I.N. Lab meeting model {} (Ollama cloud)",
                meeting.model.as_deref().unwrap_or_default()
            )
        } else {
            "R.A.I.N. Lab meeting endpoint (RAIN_LLM_BASE_URL)".to_string()
        };
        external.push(ExternalService {
            kind: "meeting".into(),
            name: what,
            refused_in_local_mode: false,
        });
    }

    if jev_enabled(ctx) {
        external.push(ExternalService {
            kind: "judgment".into(),
            name: "Jev / TypeSafe (per-request consent)".into(),
            refused_in_local_mode: false,
        });
    }

    let tunnel = ctx.config.tunnel.provider.trim();
    if !tunnel.is_empty() && tunnel != "none" {
        external.push(ExternalService {
            kind: "tunnel".into(),
            name: format!("{tunnel} tunnel"),
            refused_in_local_mode: false,
        });
    }

    for (channel, configured) in ctx.config.channels_config.channels_except_webhook() {
        if configured {
            external.push(ExternalService {
                kind: "channel".into(),
                name: channel.name().to_string(),
                refused_in_local_mode: false,
            });
        }
    }

    PrivacyStatus {
        mode,
        source,
        local_inference_enforced: ctx.config.rig.enforces_local_inference(),
        external_services: external,
        violations,
    }
}

/// The gateway/daemon listener as configured.
pub fn gateway_listener(ctx: &RigContext) -> ListenerStatus {
    let gateway = &ctx.config.gateway;
    let tunnel = ctx.config.tunnel.provider.trim();
    let tunnel = (!tunnel.is_empty() && tunnel != "none").then(|| tunnel.to_string());
    ListenerStatus {
        component: "gateway".into(),
        host: gateway.host.clone(),
        port: gateway.port,
        exposure: BindExposure::classify(&gateway.host),
        explicitly_allowed: gateway.allow_public_bind || tunnel.is_some(),
        tunnel,
    }
}

pub fn network_status(ctx: &RigContext, privacy: &PrivacyStatus) -> NetworkStatus {
    let listeners = vec![gateway_listener(ctx)];
    NetworkStatus {
        exposed_listeners: listeners
            .iter()
            .filter(|listener| !listener.exposure.is_loopback())
            .count(),
        listeners,
        external_services: privacy.external_services.len(),
    }
}

/// Probe the local gateway's `/health` endpoint (never a public host).
async fn probe_gateway(ctx: &RigContext) -> CapabilityStatus {
    let listener = gateway_listener(ctx);
    let probe_host = match listener.exposure {
        BindExposure::Loopback | BindExposure::AllInterfaces => "127.0.0.1".to_string(),
        BindExposure::PrivateNetwork => listener.host.clone(),
        BindExposure::Public => {
            return CapabilityStatus::new(
                "gateway",
                CapabilityState::Configured,
                format!("bind {} is public; not probed", listener.host),
            );
        }
    };
    let host = if probe_host.contains(':') && !probe_host.starts_with('[') {
        format!("[{probe_host}]")
    } else {
        probe_host
    };
    let outcome = ctx
        .probe
        .get(&format!("http://{host}:{}/health", listener.port), None)
        .await;
    let bind = format!(
        "{}:{} ({})",
        listener.host,
        listener.port,
        listener.exposure.label()
    );
    match outcome.status() {
        Some(200..=299) => CapabilityStatus::new(
            "gateway",
            CapabilityState::Running,
            format!("running · {bind}"),
        ),
        Some(code) => CapabilityStatus::new(
            "gateway",
            CapabilityState::Degraded,
            format!("{bind} answered /health with HTTP {code}"),
        ),
        None => CapabilityStatus::new(
            "gateway",
            CapabilityState::Unavailable,
            format!("not running · would bind {bind} (`rain rig up` or `rain daemon`)"),
        ),
    }
}

fn local_network_status(ctx: &RigContext) -> CapabilityStatus {
    let nodes = &ctx.config.nodes;
    let transport = &ctx.config.node_transport;
    let hmac_ready = transport.enabled
        && !transport.shared_secret.trim().is_empty()
        && !transport.allowed_peers.is_empty();
    match (nodes.enabled, hmac_ready) {
        (false, false) => CapabilityStatus::new(
            "local-network",
            CapabilityState::Disabled,
            "node discovery off ([nodes].enabled = false); no peer allowlist",
        ),
        (discovery, hmac) => {
            let mut parts = Vec::new();
            if discovery {
                parts.push("node discovery endpoint on the gateway".to_string());
            }
            if hmac {
                parts.push(format!(
                    "HMAC node transport with {} allowed peer(s)",
                    transport.allowed_peers.len()
                ));
            }
            CapabilityStatus::new(
                "local-network",
                CapabilityState::Configured,
                parts.join(" · "),
            )
        }
    }
}

fn hardware_statuses(ctx: &RigContext) -> Vec<CapabilityStatus> {
    let peripherals = &ctx.config.peripherals;
    let status = if !peripherals.enabled {
        CapabilityStatus::new(
            "peripherals",
            CapabilityState::Disabled,
            "[peripherals].enabled = false",
        )
    } else if peripherals.boards.is_empty() {
        CapabilityStatus::new(
            "peripherals",
            CapabilityState::Configured,
            "enabled, no boards configured",
        )
    } else {
        let boards: Vec<_> = peripherals
            .boards
            .iter()
            .map(|b| b.board.as_str())
            .collect();
        // Devices are not opened here; attaching boards is `rain peripheral`.
        CapabilityStatus::new(
            "peripherals",
            CapabilityState::Configured,
            format!("{} (devices not opened by the Rig)", boards.join(", ")),
        )
    };
    let rf = CapabilityStatus::new(
        "rf-transmit",
        CapabilityState::Disabled,
        "no radio/SDR transmit backend in this build; transmit requests are refused",
    );
    vec![status, rf]
}

fn storage_status(ctx: &RigContext) -> CapabilityStatus {
    let backend = crate::memory::effective_memory_backend_name(
        &ctx.config.memory.backend,
        Some(&ctx.config.storage.provider.config),
    );
    if backend == "none" {
        CapabilityStatus::new("memory", CapabilityState::Disabled, "memory backend: none")
    } else {
        CapabilityStatus::new(
            "memory",
            CapabilityState::Available,
            format!(
                "{backend} (auto-save: {})",
                if ctx.config.memory.auto_save {
                    "on"
                } else {
                    "off"
                }
            ),
        )
    }
}

/// Hardware, storage, and network capability statuses.
pub async fn probe_system(ctx: &RigContext) -> Vec<CapabilityStatus> {
    let mut statuses = hardware_statuses(ctx);
    statuses.push(storage_status(ctx));
    statuses.push(probe_gateway(ctx).await);
    statuses.push(local_network_status(ctx));
    statuses
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::rig::context::RigEnv;
    use crate::rig::test_support::context;

    #[test]
    fn bind_exposure_classification() {
        assert_eq!(BindExposure::classify("127.0.0.1"), BindExposure::Loopback);
        assert_eq!(BindExposure::classify("[::1]"), BindExposure::Loopback);
        assert_eq!(
            BindExposure::classify("0.0.0.0"),
            BindExposure::AllInterfaces
        );
        assert_eq!(BindExposure::classify("[::]"), BindExposure::AllInterfaces);
        assert_eq!(
            BindExposure::classify("192.168.1.3"),
            BindExposure::PrivateNetwork
        );
        assert_eq!(BindExposure::classify("203.0.113.9"), BindExposure::Public);
    }

    #[test]
    fn default_gateway_listener_is_loopback() {
        let listener = gateway_listener(&context());
        assert_eq!(listener.exposure, BindExposure::Loopback);
        assert!(!listener.explicitly_allowed);
    }

    #[test]
    fn external_bind_is_reported_prominently() {
        let mut ctx = context();
        ctx.config.gateway.host = "0.0.0.0".into();
        ctx.config.gateway.allow_public_bind = true;
        let privacy = assess_privacy(&ctx);
        let network = network_status(&ctx, &privacy);
        assert_eq!(network.exposed_listeners, 1);
        assert_eq!(network.listeners[0].exposure.label(), "ALL INTERFACES");
        assert!(network.listeners[0].explicitly_allowed);
    }

    #[test]
    fn local_privacy_flags_hosted_providers_in_chain() {
        let mut ctx = context();
        ctx.config.default_provider = Some("llamacpp".into());
        ctx.config.reliability.fallback_providers = vec!["openrouter".into()];
        ctx.config.rig.privacy = Some(RigPrivacyMode::Local);
        let privacy = assess_privacy(&ctx);
        assert!(privacy.local_inference_enforced);
        assert_eq!(privacy.violations.len(), 1, "{:?}", privacy.violations);
        assert!(privacy.violations[0].contains("openrouter"));

        ctx.config.rig.privacy = Some(RigPrivacyMode::Hybrid);
        let privacy = assess_privacy(&ctx);
        assert!(privacy.violations.is_empty());
        assert_eq!(privacy.external_services.len(), 1);
    }

    #[test]
    fn custom_provider_credentials_are_not_reported() {
        let mut ctx = context();
        ctx.config.default_provider = Some("custom:https://u:s3cret@api.example.com/v1".into());
        ctx.config.rig.privacy = Some(RigPrivacyMode::Local);
        let rendered = serde_json::to_string(&assess_privacy(&ctx)).unwrap();
        assert!(!rendered.contains("s3cret"), "{rendered}");
        assert!(rendered.contains("api.example.com"));
    }

    #[test]
    fn fully_local_config_has_no_external_services() {
        let mut ctx = context();
        ctx.config.default_provider = Some("llamacpp".into());
        ctx.config.rig.privacy = Some(RigPrivacyMode::Local);
        ctx.env = RigEnv::from_pairs([("RAIN_LLM_MODEL", "qwen3:4b")]);
        let privacy = assess_privacy(&ctx);
        assert!(
            privacy.external_services.is_empty(),
            "{:?}",
            privacy.external_services
        );
        assert!(privacy.violations.is_empty());
    }

    #[test]
    fn meeting_cloud_model_counts_as_external_service() {
        let mut ctx = context();
        ctx.config.default_provider = Some("ollama".into());
        ctx.env = RigEnv::from_pairs([("RAIN_LLM_MODEL", "minimax-m2.7:cloud")]);
        let privacy = assess_privacy(&ctx);
        assert!(
            privacy
                .external_services
                .iter()
                .any(|s| s.kind == "meeting")
        );
    }

    #[tokio::test]
    async fn gateway_not_running_is_unavailable() {
        let mut ctx = context();
        ctx.config.gateway.port = crate::rig::test_support::unused_local_port();
        let statuses = probe_system(&ctx).await;
        let gateway = statuses.iter().find(|s| s.id == "gateway").unwrap();
        assert_eq!(gateway.state, CapabilityState::Unavailable);
        let rf = statuses.iter().find(|s| s.id == "rf-transmit").unwrap();
        assert_eq!(rf.state, CapabilityState::Disabled);
    }
}
