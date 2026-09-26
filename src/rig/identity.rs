//! Privacy-safe node identity descriptor.
//!
//! This is the only thing a Rig advertises about itself to transports:
//!
//! ```json
//! { "node": "rain-local", "version": 1, "capabilities": ["research", "local-inference"] }
//! ```
//!
//! By construction it cannot carry prompts, papers, credentials, API keys,
//! hardware serial numbers, filesystem paths, endpoints, model names, or
//! personal information: the node name is validated to a DNS-label
//! alphabet and capabilities come from a fixed enum of coarse tags.

use super::capability::{CapabilityState, CapabilityStatus};
use serde::{Deserialize, Serialize};

pub const IDENTITY_VERSION: u32 = 1;

/// Coarse, shareable capability tags.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum IdentityCapability {
    Research,
    LocalInference,
    Reticulum,
    Skybridge,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NodeIdentity {
    pub node: String,
    pub version: u32,
    pub capabilities: Vec<IdentityCapability>,
}

fn usable(statuses: &[CapabilityStatus], id: &str) -> bool {
    statuses
        .iter()
        .any(|status| status.id == id && status.state.is_usable())
}

/// Build the descriptor from observed capability states.
///
/// `node_name` must already be validated (`validate_rig_node_name`).
pub fn build_identity(node_name: &str, statuses: &[CapabilityStatus]) -> NodeIdentity {
    let mut capabilities = Vec::new();
    if usable(statuses, "research-registry") {
        capabilities.push(IdentityCapability::Research);
    }
    let local_inference = statuses.iter().any(|status| {
        status.state == CapabilityState::Running
            && status.inference.as_ref().is_some_and(|detail| {
                detail.locality != "remote" && detail.provider != "rain-lab-meeting"
            })
    });
    if local_inference {
        capabilities.push(IdentityCapability::LocalInference);
    }
    if statuses
        .iter()
        .any(|status| status.id == "reticulum" && status.state == CapabilityState::Running)
    {
        capabilities.push(IdentityCapability::Reticulum);
    }
    if usable(statuses, "skybridge") {
        capabilities.push(IdentityCapability::Skybridge);
    }
    capabilities.sort();
    NodeIdentity {
        node: node_name.to_string(),
        version: IDENTITY_VERSION,
        capabilities,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::rig::capability::InferenceDetail;

    fn running_llamacpp() -> CapabilityStatus {
        CapabilityStatus::new("llamacpp", CapabilityState::Running, "ready").with_inference(
            InferenceDetail {
                provider: "llamacpp".into(),
                endpoint: Some("http://localhost:8080/v1".into()),
                locality: "local".into(),
                models: vec!["private-model-name.gguf".into()],
                ..InferenceDetail::default()
            },
        )
    }

    #[test]
    fn identity_matches_documented_shape() {
        let statuses = vec![
            CapabilityStatus::new("research-registry", CapabilityState::Available, "8 papers"),
            running_llamacpp(),
            CapabilityStatus::new("reticulum", CapabilityState::Running, "shared instance"),
        ];
        let identity = build_identity("rain-dc-01", &statuses);
        let json = serde_json::to_value(&identity).unwrap();
        assert_eq!(
            json,
            serde_json::json!({
                "node": "rain-dc-01",
                "version": 1,
                "capabilities": ["research", "local-inference", "reticulum"]
            })
        );
    }

    #[test]
    fn identity_never_leaks_paths_endpoints_models_or_secrets() {
        let statuses = vec![running_llamacpp()];
        let rendered = serde_json::to_string(&build_identity("rain-local", &statuses)).unwrap();
        for forbidden in ["http", "localhost", "8080", "gguf", "private-model", "/"] {
            assert!(
                !rendered.contains(forbidden),
                "{forbidden} leaked: {rendered}"
            );
        }
        assert_eq!(
            serde_json::to_value(build_identity("rain-local", &statuses))
                .unwrap()
                .as_object()
                .unwrap()
                .len(),
            3
        );
    }

    #[test]
    fn configured_but_not_running_services_are_not_advertised() {
        let statuses = vec![
            CapabilityStatus::new("reticulum", CapabilityState::Configured, "config found"),
            CapabilityStatus::new("research-registry", CapabilityState::Unavailable, "missing"),
        ];
        assert!(
            build_identity("rain-local", &statuses)
                .capabilities
                .is_empty()
        );
    }

    #[test]
    fn identity_rejects_unknown_fields_on_parse() {
        let raw = r#"{"node":"a","version":1,"capabilities":[],"path":"/home/x"}"#;
        assert!(serde_json::from_str::<NodeIdentity>(raw).is_err());
    }
}
