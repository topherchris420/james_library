//! Trust-related types for the security and approval subsystems.

use serde::{Deserialize, Serialize};

/// Trust level assigned to an identity or session.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum TrustLevel {
    /// No trust — all actions require explicit approval.
    #[default]
    None,
    /// Basic trust — low-risk read-only actions are auto-approved.
    Low,
    /// Medium trust — most non-destructive actions are auto-approved.
    Medium,
    /// High trust — all actions except security-critical ones are auto-approved.
    High,
    /// Full trust — all actions are auto-approved (owner/admin only).
    Full,
}

impl std::fmt::Display for TrustLevel {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::None => write!(f, "none"),
            Self::Low => write!(f, "low"),
            Self::Medium => write!(f, "medium"),
            Self::High => write!(f, "high"),
            Self::Full => write!(f, "full"),
        }
    }
}

/// A trust evaluation result with optional reasoning.
#[derive(Debug, Clone)]
pub struct TrustEvaluation {
    /// The computed trust level.
    pub level: TrustLevel,
    /// Human-readable reason for the trust decision.
    pub reason: String,
}
