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

// ── Transitions ──────────────────────────────────────────────────

/// Why a state change is being requested. Every transition has an explicit
/// trigger; there are no implicit or wildcard state changes.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum StateTrigger {
    /// A direct message or self-prompt started an agent turn.
    TurnStarted,
    /// The turn finished with healthy vitals.
    TurnCompletedHealthy,
    /// The vitals monitor escalated past redirect (yield or abort).
    VitalsEscalated,
    /// A P0 interrupt (stop command, fault signal) was observed.
    InterruptObserved,
    /// A recovery plan was selected and is starting.
    RemediationStarted,
    /// The operator acknowledged the incident out-of-band.
    OperatorAcknowledged,
    /// The recovery plan succeeded and vitals are healthy again.
    RemediationSucceeded,
    /// The recovery plan failed.
    RemediationFailed,
}

/// Snapshot of the machine at a moment, also the JSONL line schema for
/// `runtime/state_snapshots.jsonl` (Python tier tails this file).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BehavioralStateSnapshot {
    pub schema_version: u32,
    pub state: BehavioralState,
    /// RFC 3339 instant the state was entered.
    pub since: String,
    /// Last transition trigger and cause, for observability.
    pub trigger: Option<StateTrigger>,
    pub cause: String,
    /// Remediation attempts since the last healthy period.
    pub remediation_attempts: u32,
}

pub const STATE_SNAPSHOT_SCHEMA_VERSION: u32 = 1;

/// Snapshot stream path (single writer: this machine).
pub fn state_snapshots_path(workspace_dir: &std::path::Path) -> std::path::PathBuf {
    workspace_dir.join("runtime").join("state_snapshots.jsonl")
}

/// Behavioral state machine with an explicit transition table.
///
/// Invalid (state, trigger) pairs are rejected with an error — never
/// silently coerced (fail-fast, CLAUDE.md §3.5). The Alert ↔ Remediating
/// loop is bounded: after `max_remediation_attempts` failed plans the
/// machine refuses further automatic remediation until an operator
/// acknowledges.
pub struct StateMachine {
    snapshot: BehavioralStateSnapshot,
    /// When set, every transition appends a snapshot line here.
    snapshots_path: Option<std::path::PathBuf>,
    max_remediation_attempts: u32,
    tx: tokio::sync::watch::Sender<BehavioralStateSnapshot>,
}

impl StateMachine {
    /// Create a machine starting in `Idle`. When `workspace_dir` is given,
    /// transitions persist to `runtime/state_snapshots.jsonl` and the last
    /// persisted state (if any) is restored as the starting state.
    pub fn new(
        workspace_dir: Option<&std::path::Path>,
        max_remediation_attempts: u32,
    ) -> (Self, tokio::sync::watch::Receiver<BehavioralStateSnapshot>) {
        let restored = workspace_dir.and_then(Self::restore);
        let snapshot = restored.unwrap_or_else(|| BehavioralStateSnapshot {
            schema_version: STATE_SNAPSHOT_SCHEMA_VERSION,
            state: BehavioralState::Idle,
            since: chrono::Utc::now().to_rfc3339(),
            trigger: None,
            cause: "startup".to_string(),
            remediation_attempts: 0,
        });
        let (tx, rx) = tokio::sync::watch::channel(snapshot.clone());
        (
            Self {
                snapshot,
                snapshots_path: workspace_dir.map(state_snapshots_path),
                max_remediation_attempts: max_remediation_attempts.max(1),
                tx,
            },
            rx,
        )
    }

    pub fn current(&self) -> &BehavioralStateSnapshot {
        &self.snapshot
    }

    /// Restore the most recent persisted snapshot, tolerating a partial
    /// trailing line (the writer may have been interrupted mid-append).
    pub fn restore(workspace_dir: &std::path::Path) -> Option<BehavioralStateSnapshot> {
        let content = std::fs::read_to_string(state_snapshots_path(workspace_dir)).ok()?;
        content
            .lines()
            .rev()
            .find_map(|line| serde_json::from_str(line).ok())
    }

    /// Whether the machine woke up mid-incident (boot-time recall should
    /// review open episodes before accepting new work).
    pub fn resumed_mid_incident(&self) -> bool {
        self.snapshot.state.is_incident() && self.snapshot.cause != "startup"
    }

    /// Apply a trigger. Returns the new state, or an explicit error for
    /// transitions not in the table.
    #[allow(
        clippy::match_same_arms,
        reason = "one explicit arm per (state, trigger) pair keeps the transition table auditable"
    )]
    pub fn transition(
        &mut self,
        trigger: StateTrigger,
        cause: &str,
    ) -> anyhow::Result<BehavioralState> {
        use BehavioralState as S;
        use StateTrigger as T;

        let from = self.snapshot.state;
        let next = match (from, trigger) {
            (S::Idle, T::TurnStarted) => S::Thinking,
            (S::Thinking, T::TurnCompletedHealthy) => S::Idle,
            (S::Thinking, T::VitalsEscalated) => S::Alert,
            // An interrupt escalates from any state; re-entering Alert from
            // Alert is valid (refreshes cause/since).
            (_, T::InterruptObserved) => S::Alert,
            (S::Alert, T::RemediationStarted) => {
                anyhow::ensure!(
                    self.snapshot.remediation_attempts < self.max_remediation_attempts,
                    "remediation attempts exhausted ({}/{}); operator acknowledgement required",
                    self.snapshot.remediation_attempts,
                    self.max_remediation_attempts
                );
                S::Remediating
            }
            (S::Alert, T::OperatorAcknowledged) => S::Idle,
            (S::Remediating, T::RemediationSucceeded) => S::Idle,
            (S::Remediating, T::RemediationFailed) => S::Alert,
            (from, trigger) => anyhow::bail!(
                "invalid behavioral state transition: {from} + {trigger:?} is not in the table"
            ),
        };

        let attempts = match (trigger, next) {
            (T::RemediationFailed, _) => self.snapshot.remediation_attempts.saturating_add(1),
            (T::RemediationSucceeded | T::OperatorAcknowledged, _) => 0,
            _ => self.snapshot.remediation_attempts,
        };

        self.snapshot = BehavioralStateSnapshot {
            schema_version: STATE_SNAPSHOT_SCHEMA_VERSION,
            state: next,
            since: chrono::Utc::now().to_rfc3339(),
            trigger: Some(trigger),
            cause: cause.to_string(),
            remediation_attempts: attempts,
        };
        self.persist();
        let _ = self.tx.send(self.snapshot.clone());
        tracing::info!(
            from = %from,
            to = %next,
            ?trigger,
            cause,
            "behavioral state transition"
        );
        Ok(next)
    }

    /// Best-effort append; persistence failure must never block a state
    /// change (the in-memory machine stays authoritative).
    fn persist(&self) {
        let Some(path) = &self.snapshots_path else {
            return;
        };
        let result = (|| -> anyhow::Result<()> {
            if let Some(parent) = path.parent() {
                std::fs::create_dir_all(parent)?;
            }
            let mut line = serde_json::to_string(&self.snapshot)?;
            line.push('\n');
            use std::io::Write;
            std::fs::OpenOptions::new()
                .create(true)
                .append(true)
                .open(path)?
                .write_all(line.as_bytes())?;
            Ok(())
        })();
        if let Err(e) = result {
            tracing::warn!("failed to persist state snapshot: {e}");
        }
    }
}

// ── Per-state policy ─────────────────────────────────────────────

/// Tool gate applied as an **intersection** with the existing security
/// policy and per-channel filters: a gate can only remove tools, never add
/// them. Patterns are exact names or `prefix*` globs over registry keys.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ToolGate {
    /// Defer entirely to the existing SecurityPolicy/AutonomyLevel.
    All,
    /// Deny matching tools, allow the rest.
    Deny(&'static [&'static str]),
    /// Allow only matching tools.
    AllowOnly(&'static [&'static str]),
}

fn pattern_matches(pattern: &str, name: &str) -> bool {
    pattern
        .strip_suffix('*')
        .map_or(pattern == name, |prefix| name.starts_with(prefix))
}

impl ToolGate {
    pub fn permits(self, tool_name: &str) -> bool {
        match self {
            Self::All => true,
            Self::Deny(patterns) => !patterns.iter().any(|p| pattern_matches(p, tool_name)),
            Self::AllowOnly(patterns) => patterns.iter().any(|p| pattern_matches(p, tool_name)),
        }
    }

    /// Filter a tool-name list. The result is always a subset of the input:
    /// gates narrow, never widen (verified by property test).
    pub fn filter<'a>(self, names: impl IntoIterator<Item = &'a str>) -> Vec<&'a str> {
        names.into_iter().filter(|n| self.permits(n)).collect()
    }
}

/// How a behavioral state shapes the agent's posture. Enforcement wiring
/// into tool resolution lands in the follow-up phase; the policies here are
/// the reviewed source of truth it will consume.
#[derive(Debug, Clone, Copy)]
pub struct StatePolicy {
    /// Appended to the system prompt as a tone/register directive.
    pub tone_directive: &'static str,
    /// Multiplier over pacing delays (>1.0 = slower, more deliberate).
    pub pacing_factor: f64,
    pub tool_gate: ToolGate,
    /// Multiplier over `max_tool_iterations` (<1.0 = shorter leash).
    pub max_tool_iterations_factor: f64,
}

pub fn policy_for(state: BehavioralState) -> StatePolicy {
    match state {
        BehavioralState::Idle => StatePolicy {
            tone_directive: "Calm and brief; maintain ambient awareness.",
            pacing_factor: 1.0,
            tool_gate: ToolGate::All,
            max_tool_iterations_factor: 1.0,
        },
        BehavioralState::Thinking => StatePolicy {
            tone_directive: "Focused and thorough.",
            pacing_factor: 1.0,
            tool_gate: ToolGate::All,
            max_tool_iterations_factor: 1.0,
        },
        BehavioralState::Alert => StatePolicy {
            tone_directive: "Terse, factual, safety-first: state what is wrong, what was \
                 verified, and what will NOT be done automatically.",
            pacing_factor: 1.5,
            // Deny mutation/execution surfaces while alerted.
            tool_gate: ToolGate::Deny(&[
                "shell",
                "file_write",
                "file_edit",
                "git_operations",
                "browser*",
                "cloud_ops",
                "delegate",
            ]),
            max_tool_iterations_factor: 0.5,
        },
        BehavioralState::Remediating => StatePolicy {
            tone_directive: "Methodical recovery: one step, verify, report.",
            pacing_factor: 1.25,
            tool_gate: ToolGate::AllowOnly(&[
                "memory_*",
                "file_read",
                "glob_search",
                "content_search",
                "calculator",
                "cron_list",
                "cron_runs",
            ]),
            max_tool_iterations_factor: 0.75,
        },
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

    // ── Transition table ─────────────────────────────────────────

    fn machine() -> StateMachine {
        StateMachine::new(None, 3).0
    }

    #[tokio::test]
    async fn happy_path_idle_thinking_idle() {
        let mut m = machine();
        assert_eq!(
            m.transition(StateTrigger::TurnStarted, "user message")
                .unwrap(),
            BehavioralState::Thinking
        );
        assert_eq!(
            m.transition(StateTrigger::TurnCompletedHealthy, "done")
                .unwrap(),
            BehavioralState::Idle
        );
    }

    #[tokio::test]
    async fn incident_path_with_recovery() {
        let mut m = machine();
        m.transition(StateTrigger::TurnStarted, "t").unwrap();
        assert_eq!(
            m.transition(StateTrigger::VitalsEscalated, "stagnation")
                .unwrap(),
            BehavioralState::Alert
        );
        assert_eq!(
            m.transition(StateTrigger::RemediationStarted, "consolidate")
                .unwrap(),
            BehavioralState::Remediating
        );
        assert_eq!(
            m.transition(StateTrigger::RemediationSucceeded, "recovered")
                .unwrap(),
            BehavioralState::Idle
        );
        assert_eq!(m.current().remediation_attempts, 0);
    }

    #[tokio::test]
    async fn interrupt_escalates_from_any_state() {
        for setup in 0..3u8 {
            let mut m = machine();
            match setup {
                1 => {
                    m.transition(StateTrigger::TurnStarted, "t").unwrap();
                }
                2 => {
                    m.transition(StateTrigger::InterruptObserved, "stop")
                        .unwrap();
                    m.transition(StateTrigger::RemediationStarted, "r").unwrap();
                }
                _ => {}
            }
            assert_eq!(
                m.transition(StateTrigger::InterruptObserved, "stop")
                    .unwrap(),
                BehavioralState::Alert
            );
        }
    }

    #[tokio::test]
    async fn invalid_transitions_are_rejected_not_coerced() {
        let mut m = machine();
        // Idle cannot complete a turn it never started, or remediate.
        assert!(
            m.transition(StateTrigger::TurnCompletedHealthy, "x")
                .is_err()
        );
        assert!(m.transition(StateTrigger::RemediationStarted, "x").is_err());
        assert!(m.transition(StateTrigger::RemediationFailed, "x").is_err());
        assert_eq!(
            m.current().state,
            BehavioralState::Idle,
            "state unchanged on rejection"
        );

        m.transition(StateTrigger::TurnStarted, "t").unwrap();
        // Thinking cannot start a turn or remediate.
        assert!(m.transition(StateTrigger::TurnStarted, "x").is_err());
        assert!(
            m.transition(StateTrigger::OperatorAcknowledged, "x")
                .is_err()
        );
    }

    #[tokio::test]
    async fn remediation_loop_is_bounded_until_operator_ack() {
        let mut m = machine();
        m.transition(StateTrigger::InterruptObserved, "fault")
            .unwrap();
        for attempt in 1..=3u32 {
            m.transition(StateTrigger::RemediationStarted, "plan")
                .unwrap();
            m.transition(StateTrigger::RemediationFailed, "failed")
                .unwrap();
            assert_eq!(m.current().remediation_attempts, attempt);
        }
        // Fourth automatic attempt is refused: the machine waits for a human.
        let err = m
            .transition(StateTrigger::RemediationStarted, "plan")
            .unwrap_err();
        assert!(
            err.to_string()
                .contains("operator acknowledgement required")
        );
        assert_eq!(m.current().state, BehavioralState::Alert);

        // Acknowledgement resets the budget.
        m.transition(StateTrigger::OperatorAcknowledged, "ack")
            .unwrap();
        assert_eq!(m.current().remediation_attempts, 0);
    }

    #[tokio::test]
    async fn snapshots_persist_and_restore_across_restart() {
        let dir = tempfile::tempdir().unwrap();
        {
            let (mut m, _rx) = StateMachine::new(Some(dir.path()), 3);
            m.transition(StateTrigger::TurnStarted, "t").unwrap();
            m.transition(StateTrigger::VitalsEscalated, "stagnation")
                .unwrap();
        }
        let (m2, _rx) = StateMachine::new(Some(dir.path()), 3);
        assert_eq!(m2.current().state, BehavioralState::Alert);
        assert!(m2.resumed_mid_incident());

        // The persisted stream is line-parseable JSONL.
        let content = std::fs::read_to_string(state_snapshots_path(dir.path())).unwrap();
        assert_eq!(content.lines().count(), 2);
        for line in content.lines() {
            let snap: BehavioralStateSnapshot = serde_json::from_str(line).unwrap();
            assert_eq!(snap.schema_version, STATE_SNAPSHOT_SCHEMA_VERSION);
        }
    }

    #[tokio::test]
    async fn watch_channel_reflects_latest_snapshot() {
        let (mut m, rx) = StateMachine::new(None, 3);
        m.transition(StateTrigger::TurnStarted, "t").unwrap();
        assert_eq!(rx.borrow().state, BehavioralState::Thinking);
    }

    // ── Tool gate ────────────────────────────────────────────────

    const REGISTRY: &[&str] = &[
        "shell",
        "file_read",
        "file_write",
        "file_edit",
        "git_operations",
        "browser",
        "browser_open",
        "cloud_ops",
        "delegate",
        "memory_recall",
        "memory_store",
        "glob_search",
        "content_search",
        "calculator",
        "cron_list",
    ];

    #[test]
    fn gates_only_narrow_never_widen() {
        // Property: for every state, the gated set is a subset of the input
        // and `All` is the identity.
        for state in [
            BehavioralState::Idle,
            BehavioralState::Thinking,
            BehavioralState::Alert,
            BehavioralState::Remediating,
        ] {
            let gated = policy_for(state).tool_gate.filter(REGISTRY.iter().copied());
            assert!(
                gated.iter().all(|t| REGISTRY.contains(t)),
                "{state}: gate produced a tool not in the input"
            );
            assert!(gated.len() <= REGISTRY.len());
        }
        assert_eq!(
            ToolGate::All.filter(REGISTRY.iter().copied()).len(),
            REGISTRY.len()
        );
    }

    #[test]
    fn alert_gate_denies_mutation_surfaces() {
        let gate = policy_for(BehavioralState::Alert).tool_gate;
        for denied in [
            "shell",
            "file_write",
            "file_edit",
            "browser",
            "browser_open",
            "delegate",
        ] {
            assert!(!gate.permits(denied), "{denied} should be denied in Alert");
        }
        for allowed in ["file_read", "memory_recall", "content_search"] {
            assert!(
                gate.permits(allowed),
                "{allowed} should remain available in Alert"
            );
        }
    }

    #[test]
    fn remediating_gate_is_allowlist_only() {
        let gate = policy_for(BehavioralState::Remediating).tool_gate;
        assert!(gate.permits("memory_recall"));
        assert!(gate.permits("memory_store"));
        assert!(gate.permits("file_read"));
        assert!(!gate.permits("shell"));
        assert!(!gate.permits("file_write"));
        assert!(!gate.permits("git_operations"));
    }

    #[test]
    fn glob_patterns_match_prefixes_only() {
        assert!(pattern_matches("browser*", "browser_open"));
        assert!(pattern_matches("browser*", "browser"));
        assert!(!pattern_matches("browser*", "web_browser"));
        assert!(pattern_matches("shell", "shell"));
        assert!(!pattern_matches("shell", "shell_admin"));
    }
}
