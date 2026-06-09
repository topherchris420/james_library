//! Behavioral state data contract.
//!
//! This phase defines only the serializable state labels shared across the
//! episodic memory contracts (Rust ⇄ Python JSONL). The transition machine,
//! tone/pacing policies, and tool gating land in a later phase per
//! `docs/autonomous-runtime-design.md` §3.4.

use serde::{Deserialize, Serialize};
use std::fmt;

/// Coarse behavioral posture of the runtime at a moment in time.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum BehavioralState {
    /// Quiescent: listening, low-cost pulses only.
    Idle,
    /// Actively executing a turn or self-prompted task.
    Thinking,
    /// Vitals breach / interrupt / fault observed; defensive posture.
    Alert,
    /// Executing a recovery plan.
    Remediating,
}

impl BehavioralState {
    /// Alert and Remediating mark incident time: episode segmentation cuts
    /// a boundary when entering or leaving these states.
    pub fn is_incident(self) -> bool {
        matches!(self, Self::Alert | Self::Remediating)
    }
}

impl fmt::Display for BehavioralState {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Idle => write!(f, "idle"),
            Self::Thinking => write!(f, "thinking"),
            Self::Alert => write!(f, "alert"),
            Self::Remediating => write!(f, "remediating"),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn serializes_lowercase_for_cross_language_contract() {
        assert_eq!(
            serde_json::to_string(&BehavioralState::Remediating).unwrap(),
            "\"remediating\""
        );
        let parsed: BehavioralState = serde_json::from_str("\"alert\"").unwrap();
        assert_eq!(parsed, BehavioralState::Alert);
    }

    #[test]
    fn incident_states_are_alert_and_remediating() {
        assert!(BehavioralState::Alert.is_incident());
        assert!(BehavioralState::Remediating.is_incident());
        assert!(!BehavioralState::Idle.is_incident());
        assert!(!BehavioralState::Thinking.is_incident());
    }
}
