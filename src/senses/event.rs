use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

/// Priority lane for a sensory event. Lower value = served first.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum SensePriority {
    /// P0 — interrupts: operator stop commands, fault signals. Never dropped;
    /// producers block when the lane is full.
    Interrupt = 0,
    /// P1 — direct address: user messages awaiting an agent turn. Producers
    /// block when full (preserves the backpressure of the bounded mpsc the
    /// bus replaces).
    Direct = 1,
    /// P2 — environmental: webhooks, file changes, sensor threshold
    /// crossings. Oldest dropped on overflow.
    Environmental = 2,
    /// P3 — ambient telemetry: periodic readings, presence signals. Oldest
    /// dropped on overflow.
    Ambient = 3,
}

impl SensePriority {
    pub const COUNT: usize = 4;

    pub fn lane(self) -> usize {
        self as usize
    }

    pub fn from_lane(lane: usize) -> Option<Self> {
        match lane {
            0 => Some(Self::Interrupt),
            1 => Some(Self::Direct),
            2 => Some(Self::Environmental),
            3 => Some(Self::Ambient),
            _ => None,
        }
    }
}

/// What the event carries. Payloads are in-process values, not serialized:
/// channel messages can hold raw media bytes and untrusted content that must
/// never be written to logs or digests (only routing metadata is loggable).
#[derive(Debug, Clone)]
pub enum SensePayload {
    /// A message from a communication channel, forwarded verbatim to the
    /// dispatch loop.
    ChannelMessage(crate::channels::traits::ChannelMessage),
    /// A one-line ambient observation, folded into the ambient context
    /// buffer rather than starting an agent turn.
    Observation { text: String },
}

/// Unified envelope for everything the runtime perceives.
#[derive(Debug, Clone)]
pub struct SensoryEvent {
    /// Origin, e.g. `"channel:telegram"`, `"peripheral:nucleo-0"`.
    pub source: String,
    pub priority: SensePriority,
    pub observed_at: DateTime<Utc>,
    /// After this instant the event is stale and is dropped unprocessed.
    pub expires_at: Option<DateTime<Utc>>,
    /// Events sharing a key within the coalesce window fold into one (latest
    /// wins). Only honored for `Environmental`/`Ambient` priorities —
    /// interrupts and direct messages are never debounced.
    pub coalesce_key: Option<String>,
    /// How many earlier events were folded into this one (0 = none).
    pub folds: u64,
    pub payload: SensePayload,
}

impl SensoryEvent {
    pub fn new(source: impl Into<String>, priority: SensePriority, payload: SensePayload) -> Self {
        Self {
            source: source.into(),
            priority,
            observed_at: Utc::now(),
            expires_at: None,
            coalesce_key: None,
            folds: 0,
            payload,
        }
    }

    pub fn with_expiry(mut self, expires_at: DateTime<Utc>) -> Self {
        self.expires_at = Some(expires_at);
        self
    }

    pub fn with_coalesce_key(mut self, key: impl Into<String>) -> Self {
        self.coalesce_key = Some(key.into());
        self
    }

    pub fn is_expired(&self, now: DateTime<Utc>) -> bool {
        self.expires_at.is_some_and(|deadline| now > deadline)
    }
}
