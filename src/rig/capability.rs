//! Rig capability registry.
//!
//! A capability's *descriptor* (what it is, which category, whether it is
//! optional or experimental) is static and independent of its *state*
//! (whether it is running on this machine right now). Probes produce
//! [`CapabilityStatus`] values; nothing here infers state.

use serde::Serialize;

/// Capability category.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CapabilityCategory {
    Inference,
    Research,
    Decision,
    Transport,
    Radio,
    Hardware,
    Storage,
    Network,
}

impl CapabilityCategory {
    pub const ALL: [Self; 8] = [
        Self::Inference,
        Self::Research,
        Self::Decision,
        Self::Transport,
        Self::Radio,
        Self::Hardware,
        Self::Storage,
        Self::Network,
    ];

    pub fn as_str(self) -> &'static str {
        match self {
            Self::Inference => "inference",
            Self::Research => "research",
            Self::Decision => "decision",
            Self::Transport => "transport",
            Self::Radio => "radio",
            Self::Hardware => "hardware",
            Self::Storage => "storage",
            Self::Network => "network",
        }
    }
}

/// Observed capability state.
///
/// - `running`: a live probe of a service succeeded just now.
/// - `available`: present and usable on demand without a separate service
///   (compiled-in component, persona file, research corpus).
/// - `configured`: selected in configuration but not active or reachable now.
/// - `degraded`: active but failing a health check (auth rejected, loading).
/// - `disabled`: turned off by configuration or policy.
/// - `unavailable`: missing or not reachable.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CapabilityState {
    Running,
    Available,
    Configured,
    Degraded,
    Disabled,
    Unavailable,
}

impl CapabilityState {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Running => "running",
            Self::Available => "available",
            Self::Configured => "configured",
            Self::Degraded => "degraded",
            Self::Disabled => "disabled",
            Self::Unavailable => "unavailable",
        }
    }

    /// Usable right now without operator action.
    pub fn is_usable(self) -> bool {
        matches!(self, Self::Running | Self::Available)
    }

    /// Status glyph: `●` usable, `◐` degraded, `○` otherwise.
    pub fn glyph(self) -> &'static str {
        if self.is_usable() {
            "●"
        } else if self == Self::Degraded {
            "◐"
        } else {
            "○"
        }
    }
}

/// Static description of a capability.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct CapabilityDescriptor {
    pub id: &'static str,
    pub name: &'static str,
    pub category: CapabilityCategory,
    /// Optional capabilities never block the node; missing ones are `SKIP`.
    pub optional: bool,
    /// Experimental capabilities are outside the stable core.
    pub experimental: bool,
    pub summary: &'static str,
}

const fn cap(
    id: &'static str,
    name: &'static str,
    category: CapabilityCategory,
    optional: bool,
    experimental: bool,
    summary: &'static str,
) -> CapabilityDescriptor {
    CapabilityDescriptor {
        id,
        name,
        category,
        optional,
        experimental,
        summary,
    }
}

use CapabilityCategory as C;

/// Every capability the Rig knows how to discover, in display order.
pub const REGISTRY: &[CapabilityDescriptor] = &[
    cap(
        "llamacpp",
        "llama.cpp",
        C::Inference,
        true,
        false,
        "llama-server OpenAI-compatible endpoint (existing `llamacpp` provider)",
    ),
    cap(
        "ollama",
        "Ollama",
        C::Inference,
        true,
        false,
        "Ollama local model server (existing `ollama` provider)",
    ),
    cap(
        "lmstudio",
        "LM Studio",
        C::Inference,
        true,
        false,
        "LM Studio local server (existing `lmstudio` provider)",
    ),
    cap(
        "research-registry",
        "Research library",
        C::Research,
        false,
        false,
        "Papers corpus used by the R.A.I.N. Lab meeting",
    ),
    cap(
        "james",
        "James",
        C::Research,
        false,
        false,
        "Lead scientist persona (JAMES_SOUL.md)",
    ),
    cap(
        "jasmine",
        "Jasmine",
        C::Research,
        false,
        false,
        "Hardware architect persona (JASMINE_SOUL.md)",
    ),
    cap(
        "luca",
        "Luca",
        C::Research,
        false,
        false,
        "Field topographer persona (LUCA_SOUL.md)",
    ),
    cap(
        "elena",
        "Elena",
        C::Research,
        false,
        false,
        "Quantum information theorist persona (ELENA_SOUL.md)",
    ),
    cap(
        "lab-meeting",
        "Meeting inference",
        C::Research,
        true,
        false,
        "Endpoint used by `python rain_lab.py` meetings (RAIN_LLM_BASE_URL)",
    ),
    cap(
        "deterministic-validation",
        "Deterministic validation",
        C::Decision,
        false,
        false,
        "Rig action boundary: policy checks and deterministic validation before any action",
    ),
    cap(
        "laya",
        "Laya",
        C::Decision,
        true,
        false,
        "Local bounded judgment (RAIN_DECISION_MODE=laya|cascade)",
    ),
    cap(
        "jev",
        "Jev",
        C::Decision,
        true,
        false,
        "Remote TypeSafe bounded judgment (RAIN_DECISION_MODE=jev|cascade)",
    ),
    cap(
        "local",
        "Local loopback",
        C::Transport,
        false,
        false,
        "In-process loopback transport; no network listener",
    ),
    cap(
        "reticulum",
        "Reticulum",
        C::Transport,
        true,
        false,
        "Reticulum network stack (rnsd); raw packets are not bridged (messaging uses LXMF)",
    ),
    cap(
        "lxmf",
        "LXMF",
        C::Transport,
        true,
        false,
        "LXMF messaging over Reticulum via the optional R.A.I.N. bridge sidecar",
    ),
    cap(
        "skybridge",
        "Skybridge",
        C::Transport,
        true,
        true,
        "Plaintext low-bandwidth frame codec and software baseband modem",
    ),
    cap(
        "rf-transmit",
        "RF transmit",
        C::Radio,
        true,
        true,
        "Radio/SDR transmit backend; not present in this build",
    ),
    cap(
        "peripherals",
        "Peripheral boards",
        C::Hardware,
        true,
        false,
        "Configured hardware boards ([peripherals])",
    ),
    cap(
        "memory",
        "Memory backend",
        C::Storage,
        false,
        false,
        "Agent memory backend ([memory])",
    ),
    cap(
        "gateway",
        "R.A.I.N. gateway",
        C::Network,
        true,
        false,
        "Local HTTP gateway / daemon ([gateway])",
    ),
    cap(
        "local-network",
        "Local network peering",
        C::Network,
        true,
        false,
        "Node discovery ([nodes]) and HMAC node transport ([node_transport])",
    ),
];

/// Look up a registered capability.
pub fn descriptor(id: &str) -> Option<&'static CapabilityDescriptor> {
    REGISTRY.iter().find(|descriptor| descriptor.id == id)
}

/// Inference-specific facts attached to an inference capability status.
#[allow(
    clippy::struct_excessive_bools,
    reason = "independent observed facts serialized as a flat report"
)]
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize)]
pub struct InferenceDetail {
    /// Provider id as used in config (e.g. `llamacpp`).
    pub provider: String,
    /// Base URL (credentials are never included).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub endpoint: Option<String>,
    /// `local`, `lan`, or `remote`.
    pub locality: String,
    /// Whether a credential would be sent. The value itself is never reported.
    pub auth_configured: bool,
    /// Whether this is the configured `default_provider`.
    pub selected: bool,
    /// Discovered model ids, where the server supports listing.
    pub models: Vec<String>,
    /// Hosted/cloud-routed model ids reported by the server, if any.
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub hosted_models: Vec<String>,
    /// Whether a binary for this server was found on `PATH`.
    pub binary_on_path: bool,
    /// Whether a live probe was attempted (never for remote endpoints).
    pub probed: bool,
}

/// Transport-specific facts attached to a transport capability status.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize)]
pub struct TransportDetail {
    pub bidirectional: bool,
    /// Maximum payload bytes per message/frame accepted by the adapter.
    pub max_payload_bytes: usize,
    /// Whether this adapter can send in the current build.
    pub send_supported: bool,
    /// Whether any radio-frequency emission is possible (always false).
    pub rf_transmit: bool,
}

/// Observed status of one capability.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct CapabilityStatus {
    pub id: String,
    pub name: String,
    pub category: CapabilityCategory,
    pub state: CapabilityState,
    pub optional: bool,
    pub experimental: bool,
    /// One-line human explanation of the state.
    pub detail: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub inference: Option<InferenceDetail>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub transport: Option<TransportDetail>,
}

impl CapabilityStatus {
    /// Status for a registered capability.
    ///
    /// Panics in debug builds on unknown ids so typos surface in tests;
    /// release builds fall back to an optional research entry.
    pub fn new(id: &str, state: CapabilityState, detail: impl Into<String>) -> Self {
        let descriptor = descriptor(id);
        debug_assert!(descriptor.is_some(), "unregistered rig capability {id}");
        let (name, category, optional, experimental) = descriptor.map_or(
            (id, CapabilityCategory::Research, true, false),
            |descriptor| {
                (
                    descriptor.name,
                    descriptor.category,
                    descriptor.optional,
                    descriptor.experimental,
                )
            },
        );
        Self {
            id: id.to_string(),
            name: name.to_string(),
            category,
            state,
            optional,
            experimental,
            detail: detail.into(),
            inference: None,
            transport: None,
        }
    }

    /// Status for a configured provider that is not one of the registered
    /// local servers (for example `vllm` or a hosted provider).
    pub fn configured_provider(
        provider: &str,
        state: CapabilityState,
        detail: impl Into<String>,
    ) -> Self {
        Self {
            id: format!("provider:{provider}"),
            name: provider.to_string(),
            category: CapabilityCategory::Inference,
            state,
            optional: false,
            experimental: false,
            detail: detail.into(),
            inference: None,
            transport: None,
        }
    }

    #[must_use]
    pub fn with_inference(mut self, detail: InferenceDetail) -> Self {
        self.inference = Some(detail);
        self
    }

    #[must_use]
    pub fn with_transport(mut self, detail: TransportDetail) -> Self {
        self.transport = Some(detail);
        self
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashSet;

    #[test]
    fn registry_ids_are_unique_and_kebab_case() {
        let mut seen = HashSet::new();
        for descriptor in REGISTRY {
            assert!(seen.insert(descriptor.id), "duplicate id {}", descriptor.id);
            assert!(
                descriptor
                    .id
                    .bytes()
                    .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-'),
                "{}",
                descriptor.id
            );
        }
    }

    #[test]
    fn registry_covers_every_category() {
        for category in CapabilityCategory::ALL {
            assert!(
                REGISTRY.iter().any(|d| d.category == category),
                "no capability in {category:?}"
            );
        }
    }

    #[test]
    fn registry_contains_required_capabilities() {
        for id in [
            "llamacpp",
            "ollama",
            "lmstudio",
            "reticulum",
            "lxmf",
            "skybridge",
            "research-registry",
            "laya",
            "jev",
            "deterministic-validation",
        ] {
            assert!(descriptor(id).is_some(), "missing {id}");
        }
        assert!(descriptor("skybridge").unwrap().experimental);
        assert!(descriptor("reticulum").unwrap().optional);
        assert!(!descriptor("deterministic-validation").unwrap().optional);
    }

    #[test]
    fn builtin_profiles_reference_registered_capabilities() {
        for kind in crate::config::RigProfileKind::ALL {
            let profile = crate::config::builtin_rig_profile(kind).unwrap();
            for id in profile
                .preferred_inference
                .iter()
                .chain(profile.wanted_capabilities.iter())
            {
                assert!(descriptor(id).is_some(), "profile {kind} references {id}");
            }
            for id in &profile.preferred_inference {
                assert_eq!(
                    descriptor(id).unwrap().category,
                    CapabilityCategory::Inference
                );
            }
        }
    }

    #[test]
    fn state_glyphs_and_usability() {
        assert!(CapabilityState::Running.is_usable());
        assert!(CapabilityState::Available.is_usable());
        for state in [
            CapabilityState::Configured,
            CapabilityState::Degraded,
            CapabilityState::Disabled,
            CapabilityState::Unavailable,
        ] {
            assert!(!state.is_usable());
        }
        assert_eq!(CapabilityState::Running.glyph(), "●");
        assert_eq!(CapabilityState::Degraded.glyph(), "◐");
        assert_eq!(CapabilityState::Unavailable.glyph(), "○");
    }

    #[test]
    fn status_serializes_with_snake_case_state() {
        let status = CapabilityStatus::new("reticulum", CapabilityState::Unavailable, "not found");
        let json = serde_json::to_value(&status).unwrap();
        assert_eq!(json["state"], "unavailable");
        assert_eq!(json["category"], "transport");
        assert_eq!(json["optional"], true);
        assert!(json.get("inference").is_none());
    }
}
