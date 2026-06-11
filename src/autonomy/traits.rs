use async_trait::async_trait;
use std::sync::Arc;
use std::time::Duration;

/// When a pulse task wants to run.
///
/// `cadence()` is re-queried after every completed tick, so tasks may adapt
/// their own interval over time (for example the heartbeat's adaptive
/// back-off). Event-driven cadences arrive with the sensory bus; until then
/// the only supported cadence is a fixed period.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PulseCadence {
    /// Fixed wall-clock period between tick completions.
    Every(Duration),
}

impl PulseCadence {
    pub fn period(self) -> Duration {
        match self {
            Self::Every(d) => d,
        }
    }
}

/// Hard ceiling for one tick of one task, enforced by the driver rather than
/// trusted to the task: a tick exceeding `max_duration` is abandoned and
/// counted as a failure.
#[derive(Debug, Clone, Copy)]
pub struct PulseBudget {
    pub max_duration: Duration,
}

impl Default for PulseBudget {
    fn default() -> Self {
        Self {
            max_duration: Duration::from_secs(60),
        }
    }
}

/// What a tick accomplished. The driver logs outcomes; it does not interpret
/// them beyond scheduling.
#[derive(Debug, Clone)]
pub enum PulseOutcome {
    /// Nothing to do this tick.
    Quiet,
    /// Work was performed.
    Acted { summary: String },
}

/// Read-mostly capability surface handed to pulse tasks. Tasks never receive
/// mutable access to agent state; agent turns are executed through the same
/// public `crate::agent::run` path used by the scheduler and channels.
pub struct PulseContext {
    pub config: crate::config::Config,
    pub observer: Arc<dyn crate::observability::Observer>,
    /// Driver start instant, for uptime accounting.
    pub started_at: std::time::Instant,
}

/// A unit of recurring autonomous work executed by the pulse driver.
#[async_trait]
pub trait PulseTask: Send + Sync {
    /// Stable, lowercase registry key (for example `"heartbeat_md"`).
    fn name(&self) -> &str;

    /// Desired delay between tick completions. Re-queried after each tick.
    fn cadence(&self) -> PulseCadence;

    fn budget(&self) -> PulseBudget {
        PulseBudget::default()
    }

    /// One bounded unit of work. Must be cancel-safe: the driver wraps this
    /// future in a timeout and abandons it on shutdown.
    async fn on_tick(&self, ctx: &PulseContext) -> anyhow::Result<PulseOutcome>;
}
