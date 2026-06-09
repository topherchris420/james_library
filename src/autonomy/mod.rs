//! Autonomous pulse runtime: a generalized driver for recurring background
//! work, replacing single-purpose worker loops with trait-driven pulse tasks.
//!
//! Enabled via `[autonomous_runtime]` (default off). When enabled, the daemon
//! supervises [`run`] instead of the legacy heartbeat worker; the heartbeat
//! itself runs as the `heartbeat_md` pulse with identical user-visible
//! behavior. Design: `docs/autonomous-runtime-design.md`.

pub mod driver;
pub mod heartbeat_pulse;
pub mod traits;
pub mod vitals;

use anyhow::Result;
use driver::PulseDriver;
use std::sync::Arc;
use tokio_util::sync::CancellationToken;
use traits::{PulseContext, PulseTask};

/// Registered pulses plus any auxiliary watcher tasks they spawned
/// (currently only the heartbeat dead-man's switch).
struct PulseRegistry {
    pulses: Vec<Arc<dyn PulseTask>>,
    watchers: Vec<tokio::task::JoinHandle<()>>,
}

/// Build the registered pulses for this configuration. Pulses are additive:
/// each is enabled by its own subsystem config, keeping deny-by-default.
fn build_pulses(
    config: &crate::config::Config,
    observer: &Arc<dyn crate::observability::Observer>,
) -> Result<PulseRegistry> {
    let mut pulses: Vec<Arc<dyn PulseTask>> = Vec::new();
    let mut watchers: Vec<tokio::task::JoinHandle<()>> = Vec::new();

    if config.heartbeat.enabled {
        let pulse = heartbeat_pulse::HeartbeatMdPulse::new(config, Arc::clone(observer))?;
        if let Some(handle) =
            crate::daemon::spawn_deadman_watcher(config, pulse.metrics(), pulse.delivery())
        {
            watchers.push(handle);
        }
        pulses.push(Arc::new(pulse));
    }

    Ok(PulseRegistry { pulses, watchers })
}

/// Entry point supervised by the daemon (`autonomy` component). Runs until
/// the process shuts down; the supervisor restarts it on error with backoff.
pub async fn run(config: crate::config::Config) -> Result<()> {
    let observer: Arc<dyn crate::observability::Observer> =
        Arc::from(crate::observability::create_observer(&config.observability));

    let PulseRegistry { pulses, watchers } = build_pulses(&config, &observer)?;
    let max_concurrent = config.autonomous_runtime.max_concurrent_pulses;

    let ctx = Arc::new(PulseContext {
        config,
        observer,
        started_at: std::time::Instant::now(),
    });

    // The daemon supervisor stops this component by aborting its task; the
    // token exists for structured shutdown of in-flight ticks and for tests.
    let shutdown = CancellationToken::new();
    let driver = PulseDriver::new(pulses, ctx, max_concurrent, shutdown);

    let result = driver.run().await;
    for watcher in watchers {
        watcher.abort();
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn build_pulses_empty_when_heartbeat_disabled() {
        let config = crate::config::Config::default();
        let observer: Arc<dyn crate::observability::Observer> =
            Arc::new(crate::observability::NoopObserver);
        let registry = build_pulses(&config, &observer).unwrap();
        assert!(registry.pulses.is_empty());
        assert!(registry.watchers.is_empty());
    }

    #[tokio::test]
    async fn build_pulses_registers_heartbeat_when_enabled() {
        let mut config = crate::config::Config::default();
        config.heartbeat.enabled = true;
        let observer: Arc<dyn crate::observability::Observer> =
            Arc::new(crate::observability::NoopObserver);
        let registry = build_pulses(&config, &observer).unwrap();
        assert_eq!(registry.pulses.len(), 1);
        assert_eq!(registry.pulses[0].name(), "heartbeat_md");
        // Dead-man watcher disabled by default (timeout 0).
        assert!(registry.watchers.is_empty());
    }

    #[tokio::test]
    async fn build_pulses_spawns_deadman_watcher_when_configured() {
        let mut config = crate::config::Config::default();
        config.heartbeat.enabled = true;
        config.heartbeat.deadman_timeout_minutes = 10;
        let observer: Arc<dyn crate::observability::Observer> =
            Arc::new(crate::observability::NoopObserver);
        let registry = build_pulses(&config, &observer).unwrap();
        assert_eq!(registry.pulses.len(), 1);
        assert_eq!(registry.watchers.len(), 1);
        for w in registry.watchers {
            w.abort();
        }
    }
}
