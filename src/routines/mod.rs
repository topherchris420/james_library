//! Event-triggered automation engine.
//!
//! Routines are configured via `routines.toml` and match webhook, channel,
//! cron, or system events to fire actions (SOP triggers, shell commands,
//! messages, cron jobs). Each routine supports per-routine cooldown.

pub mod engine;
pub mod event_matcher;

use serde::{Deserialize, Serialize};

/// A single automation routine.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Routine {
    /// Human-readable name.
    pub name: String,
    /// Description of what this routine does.
    pub description: Option<String>,
    /// Event pattern that triggers this routine.
    pub event: EventPattern,
    /// Action to take when the event matches.
    pub action: RoutineAction,
    /// Minimum seconds between consecutive firings.
    #[serde(default)]
    pub cooldown_secs: u64,
    /// Whether this routine is enabled.
    #[serde(default = "default_true")]
    pub enabled: bool,
}

fn default_true() -> bool {
    true
}

/// Pattern to match against incoming events.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EventPattern {
    /// Event source (e.g. "webhook", "channel", "cron", "system").
    pub source: String,
    /// Match strategy for the pattern.
    #[serde(default)]
    pub strategy: MatchStrategy,
    /// Pattern string to match against the event payload.
    pub pattern: String,
}

/// Strategy for matching event patterns.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum MatchStrategy {
    /// Exact string match.
    #[default]
    Exact,
    /// Glob pattern match.
    Glob,
    /// Regular expression match.
    Regex,
}

/// Action to execute when a routine triggers.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum RoutineAction {
    /// Trigger an SOP by name.
    Sop { name: String },
    /// Execute a shell command.
    Shell { command: String },
    /// Send a message to a channel.
    Message { channel: String, content: String },
    /// Schedule a cron job.
    Cron { expression: String, command: String },
}

/// Result of dispatching a routine.
#[derive(Debug)]
pub struct RoutineDispatchResult {
    /// Name of the routine that fired.
    pub routine_name: String,
    /// Whether the action executed successfully.
    pub success: bool,
    /// Output or error message.
    pub message: String,
}

/// An event that can trigger routines.
#[derive(Debug, Clone)]
pub struct RoutineEvent {
    /// Source of the event.
    pub source: String,
    /// Event payload for pattern matching.
    pub payload: String,
}
