//! `rain rig status`: one typed snapshot of the node.

use super::capability::{CapabilityCategory, CapabilityState, CapabilityStatus};
use super::context::{RigContext, selected_provider};
use super::identity::{NodeIdentity, build_identity};
use super::system::{NetworkStatus, PrivacyStatus, assess_privacy, network_status};
use super::{inference, research, system, transport};
use crate::config::{RigPrivacyMode, RigProfileKind, builtin_rig_profile};
use serde::Serialize;

pub const STATUS_SCHEMA_VERSION: u32 = 1;

/// Overall node readiness.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NodeReadiness {
    /// Everything required is usable.
    Ready,
    /// Usable, but something expected is missing or unhealthy.
    Degraded,
    /// Configuration contradicts policy (for example hosted inference in
    /// local privacy mode); the runtime will refuse to start it.
    Blocked,
}

impl NodeReadiness {
    pub fn label(self) -> &'static str {
        match self {
            Self::Ready => "READY",
            Self::Degraded => "DEGRADED",
            Self::Blocked => "BLOCKED",
        }
    }
}

/// Runtime and profile facts.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct RuntimeInfo {
    pub version: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub profile: Option<RigProfileKind>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub profile_summary: Option<String>,
    pub library_found: bool,
    pub default_provider: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub default_model: Option<String>,
}

/// Full node snapshot (the `--json` document).
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct RigStatus {
    pub schema_version: u32,
    pub identity: NodeIdentity,
    pub runtime: RuntimeInfo,
    pub privacy: PrivacyStatus,
    pub network: NetworkStatus,
    pub capabilities: Vec<CapabilityStatus>,
    pub readiness: NodeReadiness,
    /// Why the node is degraded or blocked.
    pub reasons: Vec<String>,
    /// Things an operator should see even when ready (external binds).
    pub notices: Vec<String>,
}

impl RigStatus {
    pub fn get(&self, id: &str) -> Option<&CapabilityStatus> {
        self.capabilities.iter().find(|status| status.id == id)
    }

    pub fn in_category(
        &self,
        category: CapabilityCategory,
    ) -> impl Iterator<Item = &CapabilityStatus> {
        self.capabilities
            .iter()
            .filter(move |status| status.category == category)
    }

    /// The configured default provider's status.
    pub fn selected_inference(&self) -> Option<&CapabilityStatus> {
        self.capabilities.iter().find(|status| {
            status
                .inference
                .as_ref()
                .is_some_and(|detail| detail.selected)
        })
    }
}

/// Probe every capability concurrently.
pub async fn collect_capabilities(ctx: &RigContext) -> Vec<CapabilityStatus> {
    let (inference, research, system, transports) = tokio::join!(
        inference::probe_all(ctx),
        research::probe_research(ctx),
        system::probe_system(ctx),
        transport::discovery::probe_transports(ctx),
    );
    let mut capabilities = inference;
    capabilities.extend(research);
    capabilities.extend(research::probe_decision(ctx));
    capabilities.extend(transports);
    capabilities.extend(system);
    // Stable sort keeps registry order within a category.
    capabilities.sort_by_key(|status| status.category);
    capabilities
}

fn is_local_running_inference(status: &CapabilityStatus) -> bool {
    status.state == CapabilityState::Running
        && status.inference.as_ref().is_some_and(|detail| {
            detail.locality != "remote" && detail.provider != "rain-lab-meeting"
        })
}

/// Decide readiness from observed state (pure; unit-tested).
pub fn assess_readiness(
    ctx: &RigContext,
    capabilities: &[CapabilityStatus],
    privacy: &PrivacyStatus,
    network: &NetworkStatus,
) -> (NodeReadiness, Vec<String>, Vec<String>) {
    let mut reasons = Vec::new();
    let mut notices = Vec::new();
    let mut blocked = !privacy.violations.is_empty();
    reasons.extend(privacy.violations.iter().cloned());

    let selected = capabilities.iter().find(|status| {
        status
            .inference
            .as_ref()
            .is_some_and(|detail| detail.selected)
    });
    let mut degraded = false;
    if let Some(status) = selected {
        let hosted_not_probed = status.state == CapabilityState::Configured
            && status
                .inference
                .as_ref()
                .is_some_and(|detail| !detail.probed);
        if !status.state.is_usable() && !hosted_not_probed {
            degraded = true;
            reasons.push(format!(
                "default provider {} is {}: {}",
                status.name,
                status.state.as_str(),
                status.detail
            ));
        }
    }

    if privacy.mode == RigPrivacyMode::Local && !capabilities.iter().any(is_local_running_inference)
    {
        degraded = true;
        reasons.push("privacy is local-only but no local inference server is running".into());
    }

    for status in capabilities {
        if !status.optional && status.inference.is_none() && !status.state.is_usable() {
            degraded = true;
            reasons.push(format!("{}: {}", status.name, status.detail));
        }
    }

    if let Some(kind) = ctx.config.rig.profile {
        if let Ok(profile) = builtin_rig_profile(kind) {
            for id in &profile.wanted_capabilities {
                let satisfied = capabilities.iter().any(|status| {
                    status.id == *id
                        && matches!(
                            status.state,
                            CapabilityState::Running
                                | CapabilityState::Available
                                | CapabilityState::Configured
                        )
                });
                if !satisfied {
                    degraded = true;
                    reasons.push(format!(
                        "profile '{kind}' expects '{id}', which is not present"
                    ));
                }
            }
        }
    }

    for listener in &network.listeners {
        if listener.exposure.is_loopback() {
            continue;
        }
        let message = format!(
            "EXTERNAL BIND: {} {}:{} ({})",
            listener.component,
            listener.host,
            listener.port,
            listener.exposure.label()
        );
        if listener.explicitly_allowed {
            notices.push(message);
        } else {
            blocked = true;
            reasons.push(format!(
                "{message} without [gateway] allow_public_bind or a tunnel; the gateway will refuse to start"
            ));
        }
    }
    if let Some(tunnel) = network.listeners.iter().find_map(|l| l.tunnel.as_deref()) {
        notices.push(format!("gateway is published through the {tunnel} tunnel"));
    }

    let readiness = if blocked {
        NodeReadiness::Blocked
    } else if degraded {
        NodeReadiness::Degraded
    } else {
        NodeReadiness::Ready
    };
    (readiness, reasons, notices)
}

/// Collect the full status snapshot.
pub async fn collect(ctx: &RigContext) -> RigStatus {
    let capabilities = collect_capabilities(ctx).await;
    let privacy = assess_privacy(ctx);
    let network = network_status(ctx, &privacy);
    let identity = build_identity(ctx.config.rig.node_name(), &capabilities);
    let (readiness, reasons, notices) = assess_readiness(ctx, &capabilities, &privacy, &network);
    let profile = ctx.config.rig.profile;
    RigStatus {
        schema_version: STATUS_SCHEMA_VERSION,
        identity,
        runtime: RuntimeInfo {
            version: env!("CARGO_PKG_VERSION").to_string(),
            profile,
            profile_summary: profile
                .and_then(|kind| builtin_rig_profile(kind).ok())
                .map(|profile| profile.summary.clone()),
            library_found: ctx.library_root.is_some(),
            default_provider: crate::providers::locality::display_provider_id(&selected_provider(
                &ctx.config,
            )),
            default_model: ctx.config.default_model.clone(),
        },
        privacy,
        network,
        capabilities,
        readiness,
        reasons,
        notices,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::rig::test_support::{context, context_with_endpoints};
    use wiremock::matchers::{method, path};
    use wiremock::{Mock, MockServer, ResponseTemplate};

    #[tokio::test]
    async fn status_with_nothing_installed_is_useful_and_serializable() {
        let ctx = context();
        let status = collect(&ctx).await;
        for id in [
            "llamacpp",
            "ollama",
            "lmstudio",
            "reticulum",
            "lxmf",
            "skybridge",
            "laya",
            "jev",
        ] {
            assert!(status.get(id).is_some(), "missing {id}");
        }
        assert_eq!(
            status.get("llamacpp").unwrap().state,
            CapabilityState::Unavailable
        );
        assert_eq!(
            status.get("rf-transmit").unwrap().state,
            CapabilityState::Disabled
        );
        let json = serde_json::to_value(&status).unwrap();
        assert_eq!(json["schema_version"], 1);
        assert_eq!(json["identity"]["node"], "rain-local");
        assert_eq!(json["privacy"]["mode"], "hybrid");
        assert!(json["capabilities"].as_array().unwrap().len() >= 20);
        // Default config uses a hosted provider, so the node is not blocked.
        assert_ne!(status.readiness, NodeReadiness::Blocked);
    }

    #[tokio::test]
    async fn mocked_llamacpp_node_in_local_mode_is_ready() {
        let server = MockServer::start().await;
        Mock::given(method("GET"))
            .and(path("/v1/models"))
            .respond_with(
                ResponseTemplate::new(200)
                    .set_body_json(serde_json::json!({"data": [{"id": "Qwen3-4B-Q4_K_M.gguf"}]})),
            )
            .mount(&server)
            .await;
        let dir = tempfile::tempdir().unwrap();
        crate::rig::test_support::write_library(dir.path());
        let mut ctx = context_with_endpoints(Some(format!("{}/v1", server.uri())), None, None);
        ctx.library_root = Some(dir.path().to_path_buf());
        ctx.config.default_provider = Some("llamacpp".into());
        ctx.config.rig.privacy = Some(RigPrivacyMode::Local);
        let status = collect(&ctx).await;
        assert_eq!(
            status.readiness,
            NodeReadiness::Ready,
            "{:?}",
            status.reasons
        );
        assert_eq!(
            status
                .selected_inference()
                .unwrap()
                .inference
                .as_ref()
                .unwrap()
                .models,
            vec!["Qwen3-4B-Q4_K_M.gguf".to_string()]
        );
        assert!(
            status
                .identity
                .capabilities
                .contains(&crate::rig::identity::IdentityCapability::LocalInference)
        );
        assert_eq!(status.network.external_services, 0);
    }

    #[tokio::test]
    async fn local_mode_with_hosted_default_is_blocked() {
        let mut ctx = context();
        ctx.config.default_provider = Some("anthropic".into());
        ctx.config.rig.privacy = Some(RigPrivacyMode::Local);
        let status = collect(&ctx).await;
        assert_eq!(status.readiness, NodeReadiness::Blocked);
        assert!(status.reasons.iter().any(|r| r.contains("anthropic")));
    }

    #[tokio::test]
    async fn configured_but_unreachable_llamacpp_is_degraded() {
        let mut ctx = context();
        ctx.config.default_provider = Some("llamacpp".into());
        let status = collect(&ctx).await;
        assert_eq!(status.readiness, NodeReadiness::Degraded);
        assert!(
            status.reasons.iter().any(|r| r.contains("llama.cpp")),
            "{:?}",
            status.reasons
        );
    }

    #[tokio::test]
    async fn explicit_public_bind_is_a_notice_and_implicit_one_blocks() {
        let mut ctx = context();
        ctx.config.gateway.host = "0.0.0.0".into();
        let status = collect(&ctx).await;
        assert_eq!(status.readiness, NodeReadiness::Blocked);
        ctx.config.gateway.allow_public_bind = true;
        let status = collect(&ctx).await;
        assert!(status.notices.iter().any(|n| n.contains("EXTERNAL BIND")));
    }

    #[test]
    fn field_profile_expects_transports() {
        let mut ctx = context();
        ctx.config.rig.profile = Some(RigProfileKind::Field);
        let capabilities = vec![
            CapabilityStatus::new("reticulum", CapabilityState::Unavailable, "not installed"),
            CapabilityStatus::new("lxmf", CapabilityState::Configured, "config found"),
            CapabilityStatus::new("skybridge", CapabilityState::Available, "software"),
        ];
        let privacy = assess_privacy(&ctx);
        let network = network_status(&ctx, &privacy);
        let (readiness, reasons, _) = assess_readiness(&ctx, &capabilities, &privacy, &network);
        assert!(
            reasons.iter().any(|r| r.contains("'reticulum'")),
            "{reasons:?}"
        );
        assert!(!reasons.iter().any(|r| r.contains("'lxmf'")));
        assert!(!reasons.iter().any(|r| r.contains("'skybridge'")));
        // The field profile defaults to local privacy; the hosted default provider blocks.
        assert_eq!(readiness, NodeReadiness::Blocked);
    }
}
