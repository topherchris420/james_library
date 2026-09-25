//! `[rig]` — optional R.A.I.N. Rig appliance settings.
//!
//! The section is additive: omitting it keeps every pre-Rig behavior unchanged
//! (no profile, `hybrid` privacy, no inference locality enforcement).
//!
//! Built-in profiles are human-readable TOML files embedded at compile time
//! from `rig_profiles/`. Profiles only alter Rig defaults (privacy mode,
//! preferred local inference, expected optional capabilities); their schema
//! has no fields for security, autonomy, or bind policy, so a profile cannot
//! widen those boundaries.

use anyhow::{Result, bail};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use std::sync::OnceLock;

/// Default shareable node name used when `[rig].node_name` is unset.
pub const DEFAULT_RIG_NODE_NAME: &str = "rain-local";

const MAX_NODE_NAME_LEN: usize = 32;

/// Built-in Rig profile selector.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "lowercase")]
pub enum RigProfileKind {
    /// Laptop/desktop running local inference.
    Local,
    /// Always-on mini PC or home server.
    Node,
    /// Local inference plus optional low-bandwidth transports.
    Field,
}

impl RigProfileKind {
    pub const ALL: [Self; 3] = [Self::Local, Self::Node, Self::Field];

    pub fn as_str(self) -> &'static str {
        match self {
            Self::Local => "local",
            Self::Node => "node",
            Self::Field => "field",
        }
    }

    pub fn parse(raw: &str) -> Option<Self> {
        match raw.trim().to_ascii_lowercase().as_str() {
            "local" => Some(Self::Local),
            "node" => Some(Self::Node),
            "field" => Some(Self::Field),
            _ => None,
        }
    }

    fn embedded_toml(self) -> &'static str {
        match self {
            Self::Local => include_str!("rig_profiles/local.toml"),
            Self::Node => include_str!("rig_profiles/node.toml"),
            Self::Field => include_str!("rig_profiles/field.toml"),
        }
    }
}

impl std::fmt::Display for RigProfileKind {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

/// Inference privacy mode.
///
/// - `local`: every inference provider in the runtime chain (primary,
///   fallbacks, model routes, delegates) must resolve to a loopback or
///   private-network endpoint. Anything else fails closed at provider
///   construction; there is no silent hosted fallback.
/// - `hybrid`: local-first, hosted providers allowed when explicitly
///   configured. This is the pre-Rig behavior and the default.
/// - `hosted`: hosted inference is expected; enforcement matches `hybrid`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "lowercase")]
pub enum RigPrivacyMode {
    Local,
    Hybrid,
    Hosted,
}

impl RigPrivacyMode {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Local => "local",
            Self::Hybrid => "hybrid",
            Self::Hosted => "hosted",
        }
    }

    pub fn parse(raw: &str) -> Option<Self> {
        match raw.trim().to_ascii_lowercase().as_str() {
            "local" => Some(Self::Local),
            "hybrid" => Some(Self::Hybrid),
            "hosted" => Some(Self::Hosted),
            _ => None,
        }
    }

    /// Human label used by status views.
    pub fn label(self) -> &'static str {
        match self {
            Self::Local => "local-only",
            Self::Hybrid => "local-first (hosted allowed)",
            Self::Hosted => "hosted",
        }
    }
}

impl std::fmt::Display for RigPrivacyMode {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

/// Where a privacy decision came from, for status and doctor output.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RigPrivacySource {
    /// `[rig].privacy` was set explicitly.
    Explicit,
    /// Derived from the selected `[rig].profile`.
    Profile,
    /// No `[rig]` privacy or profile: pre-Rig behavior.
    Default,
}

/// Optional R.A.I.N. Rig configuration (`[rig]`).
///
/// Compatibility: additive; omitted from generated config files while unset.
/// Rollback: delete the `[rig]` table to restore pre-Rig behavior.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct RigConfig {
    /// Built-in profile: `local`, `node`, or `field`. Unset means no profile.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub profile: Option<RigProfileKind>,
    /// Shareable node name advertised in the privacy-safe identity descriptor.
    /// Lowercase letters, digits, and `-`; 1–32 characters. Default: `rain-local`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub node_name: Option<String>,
    /// Inference privacy mode: `local`, `hybrid`, or `hosted`. Unset uses the
    /// profile default, or `hybrid` (pre-Rig behavior) when no profile is set.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub privacy: Option<RigPrivacyMode>,
}

impl RigConfig {
    /// True when the section carries no settings (kept out of generated config).
    pub fn is_unset(&self) -> bool {
        self == &Self::default()
    }

    /// Effective node name (validated at config load).
    pub fn node_name(&self) -> &str {
        self.node_name
            .as_deref()
            .map(str::trim)
            .filter(|name| !name.is_empty())
            .unwrap_or(DEFAULT_RIG_NODE_NAME)
    }

    /// Effective privacy mode and where it came from.
    ///
    /// Fails closed: if a selected built-in profile cannot be loaded, the
    /// strictest mode (`local`) is returned rather than the permissive default.
    pub fn effective_privacy(&self) -> (RigPrivacyMode, RigPrivacySource) {
        if let Some(mode) = self.privacy {
            return (mode, RigPrivacySource::Explicit);
        }
        if let Some(kind) = self.profile {
            let mode = builtin_rig_profile(kind)
                .map(|profile| profile.privacy)
                .unwrap_or(RigPrivacyMode::Local);
            return (mode, RigPrivacySource::Profile);
        }
        (RigPrivacyMode::Hybrid, RigPrivacySource::Default)
    }

    /// Whether provider construction must refuse non-local inference endpoints.
    pub fn enforces_local_inference(&self) -> bool {
        self.effective_privacy().0 == RigPrivacyMode::Local
    }

    pub fn validate(&self) -> Result<()> {
        if let Some(name) = self.node_name.as_deref() {
            validate_rig_node_name(name)?;
        }
        if let Some(kind) = self.profile {
            builtin_rig_profile(kind)?;
        }
        Ok(())
    }
}

/// Validate a shareable node name: DNS-label style, 1–32 chars.
///
/// The restricted alphabet keeps names free of paths, e-mail addresses, and
/// other identifying free text before they are advertised to transports.
pub fn validate_rig_node_name(name: &str) -> Result<()> {
    let trimmed = name.trim();
    if trimmed.is_empty() || trimmed.len() > MAX_NODE_NAME_LEN {
        bail!("rig.node_name must be 1-{MAX_NODE_NAME_LEN} characters (got {trimmed:?})");
    }
    let valid_chars = trimmed
        .bytes()
        .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-');
    if !valid_chars || trimmed.starts_with('-') || trimmed.ends_with('-') {
        bail!(
            "rig.node_name may only contain lowercase letters, digits, and inner '-' (got {trimmed:?})"
        );
    }
    Ok(())
}

/// A built-in Rig profile parsed from its embedded TOML definition.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RigProfile {
    pub name: RigProfileKind,
    pub summary: String,
    pub privacy: RigPrivacyMode,
    pub always_on: bool,
    /// Local inference provider ids, in preference order.
    pub preferred_inference: Vec<String>,
    /// Optional capability ids this profile expects to be present.
    pub wanted_capabilities: Vec<String>,
}

impl RigProfile {
    /// Parse and validate a profile definition.
    pub fn parse_toml(raw: &str) -> Result<Self> {
        let profile: Self = toml::from_str(raw)
            .map_err(|error| anyhow::anyhow!("invalid rig profile definition: {error}"))?;
        if profile.summary.trim().is_empty() {
            bail!("rig profile '{}' must have a summary", profile.name);
        }
        let ids = profile
            .preferred_inference
            .iter()
            .chain(profile.wanted_capabilities.iter());
        for id in ids {
            let valid = !id.is_empty()
                && id
                    .bytes()
                    .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-');
            if !valid {
                bail!("rig profile '{}' has invalid id {id:?}", profile.name);
            }
        }
        Ok(profile)
    }
}

/// Load a built-in profile. Definitions are parsed once and cached.
pub fn builtin_rig_profile(kind: RigProfileKind) -> Result<&'static RigProfile> {
    static PROFILES: OnceLock<Vec<std::result::Result<RigProfile, String>>> = OnceLock::new();
    let parsed = PROFILES.get_or_init(|| {
        RigProfileKind::ALL
            .iter()
            .map(|kind| {
                RigProfile::parse_toml(kind.embedded_toml())
                    .map_err(|error| error.to_string())
                    .and_then(|profile| {
                        if profile.name == *kind {
                            Ok(profile)
                        } else {
                            Err(format!(
                                "rig profile file for '{kind}' declares name '{}'",
                                profile.name
                            ))
                        }
                    })
            })
            .collect()
    });
    let index = RigProfileKind::ALL
        .iter()
        .position(|candidate| *candidate == kind)
        .unwrap_or_default();
    match &parsed[index] {
        Ok(profile) => Ok(profile),
        Err(error) => bail!("{error}"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rig_config_defaults_preserve_pre_rig_behavior() {
        let config = RigConfig::default();
        assert!(config.is_unset());
        assert_eq!(config.node_name(), DEFAULT_RIG_NODE_NAME);
        assert_eq!(
            config.effective_privacy(),
            (RigPrivacyMode::Hybrid, RigPrivacySource::Default)
        );
        assert!(!config.enforces_local_inference());
    }

    #[test]
    fn rig_profiles_parse_and_default_to_local_privacy() {
        for kind in RigProfileKind::ALL {
            let profile = builtin_rig_profile(kind).expect("builtin profile parses");
            assert_eq!(profile.name, kind);
            assert_eq!(profile.privacy, RigPrivacyMode::Local);
            assert!(!profile.preferred_inference.is_empty());
        }
        assert!(builtin_rig_profile(RigProfileKind::Node).unwrap().always_on);
        let field = builtin_rig_profile(RigProfileKind::Field).unwrap();
        assert!(field.wanted_capabilities.iter().any(|id| id == "skybridge"));
    }

    #[test]
    fn rig_profile_selection_enables_local_inference_enforcement() {
        let config = RigConfig {
            profile: Some(RigProfileKind::Field),
            ..RigConfig::default()
        };
        assert_eq!(
            config.effective_privacy(),
            (RigPrivacyMode::Local, RigPrivacySource::Profile)
        );
        assert!(config.enforces_local_inference());
    }

    #[test]
    fn rig_explicit_privacy_overrides_profile_default() {
        let config = RigConfig {
            profile: Some(RigProfileKind::Local),
            privacy: Some(RigPrivacyMode::Hybrid),
            ..RigConfig::default()
        };
        assert_eq!(
            config.effective_privacy(),
            (RigPrivacyMode::Hybrid, RigPrivacySource::Explicit)
        );
        assert!(!config.enforces_local_inference());
    }

    #[test]
    fn rig_profile_rejects_unknown_fields() {
        let raw = r#"
name = "local"
summary = "x"
privacy = "local"
always_on = false
preferred_inference = ["llamacpp"]
wanted_capabilities = []
allow_public_bind = true
"#;
        let error = RigProfile::parse_toml(raw).unwrap_err().to_string();
        assert!(error.contains("allow_public_bind"), "{error}");
    }

    #[test]
    fn rig_profile_rejects_invalid_ids_and_missing_summary() {
        let bad_id = r#"
name = "node"
summary = "x"
privacy = "local"
always_on = true
preferred_inference = ["Llama CPP"]
wanted_capabilities = []
"#;
        assert!(RigProfile::parse_toml(bad_id).is_err());
        let no_summary = bad_id
            .replace("\"Llama CPP\"", "\"llamacpp\"")
            .replace("summary = \"x\"", "summary = \"  \"");
        assert!(RigProfile::parse_toml(&no_summary).is_err());
    }

    #[test]
    fn rig_config_parses_from_toml_and_rejects_unknown_keys() {
        let parsed: RigConfig =
            toml::from_str("profile = \"node\"\nnode_name = \"lab-node-1\"\nprivacy = \"local\"")
                .unwrap();
        assert_eq!(parsed.profile, Some(RigProfileKind::Node));
        assert_eq!(parsed.node_name(), "lab-node-1");
        parsed.validate().unwrap();

        assert!(toml::from_str::<RigConfig>("profile = \"cloud\"").is_err());
        assert!(toml::from_str::<RigConfig>("privacy = \"remote\"").is_err());
        assert!(toml::from_str::<RigConfig>("bind = \"0.0.0.0\"").is_err());
    }

    #[test]
    fn rig_section_is_omitted_until_set_and_round_trips() {
        let config = crate::config::Config::default();
        let rendered = toml::to_string(&config).unwrap();
        assert!(
            !rendered.contains("[rig]"),
            "unset [rig] must not be written"
        );

        let mut with_rig = config.clone();
        with_rig.rig.profile = Some(RigProfileKind::Local);
        with_rig.rig.node_name = Some("bench-node".into());
        let rendered = toml::to_string(&with_rig).unwrap();
        assert!(rendered.contains("[rig]"));
        let parsed: crate::config::Config = toml::from_str(&rendered).unwrap();
        assert_eq!(parsed.rig, with_rig.rig);
        parsed.validate().unwrap();
    }

    #[test]
    fn rig_invalid_node_name_fails_config_validation() {
        let mut config = crate::config::Config::default();
        config.rig.node_name = Some("Not Valid".into());
        let error = config.validate().unwrap_err().to_string();
        assert!(error.contains("rig.node_name"), "{error}");
    }

    #[test]
    fn rig_node_name_validation_rejects_identifying_text() {
        for ok in ["rain-local", "node1", "a", "field-kit-07"] {
            validate_rig_node_name(ok).unwrap();
        }
        for bad in [
            "",
            "-lead",
            "trail-",
            "Upper",
            "has space",
            "user@example.com",
            "/home/user",
            "x".repeat(33).as_str(),
        ] {
            assert!(validate_rig_node_name(bad).is_err(), "{bad:?} should fail");
        }
    }
}
