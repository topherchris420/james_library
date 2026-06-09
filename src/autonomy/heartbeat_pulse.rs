use super::traits::{PulseBudget, PulseCadence, PulseContext, PulseOutcome, PulseTask};
use crate::config::Config;
use crate::heartbeat::engine::{HeartbeatEngine, HeartbeatMetrics, compute_adaptive_interval};
use anyhow::Result;
use async_trait::async_trait;
use std::sync::Arc;
use std::sync::atomic::{AtomicU32, Ordering};
use std::time::Duration;

/// The existing HEARTBEAT.md heartbeat, wrapped as a pulse task.
///
/// Behavior is identical to the legacy worker: task collection and two-phase
/// decision via `daemon::heartbeat_tick`, adaptive interval back-off, and the
/// same delivery/dead-man configuration. Only the scheduling loop moved into
/// the pulse driver.
pub struct HeartbeatMdPulse {
    engine: HeartbeatEngine,
    metrics: Arc<parking_lot::Mutex<HeartbeatMetrics>>,
    delivery: Option<(String, String)>,
    /// Current interval in minutes; updated after each tick in adaptive mode.
    interval_minutes: AtomicU32,
}

impl HeartbeatMdPulse {
    pub fn new(config: &Config, observer: Arc<dyn crate::observability::Observer>) -> Result<Self> {
        let engine = HeartbeatEngine::new(
            config.heartbeat.clone(),
            config.workspace_dir.clone(),
            observer,
        );
        let metrics = engine.metrics();
        let delivery = crate::daemon::resolve_heartbeat_delivery(config)?;
        Ok(Self {
            engine,
            metrics,
            delivery,
            interval_minutes: AtomicU32::new(config.heartbeat.interval_minutes.max(5)),
        })
    }

    /// Shared handle to the live heartbeat metrics (consumed by the dead-man
    /// watcher and health surfaces).
    pub fn metrics(&self) -> Arc<parking_lot::Mutex<HeartbeatMetrics>> {
        Arc::clone(&self.metrics)
    }

    pub fn delivery(&self) -> Option<(String, String)> {
        self.delivery.clone()
    }
}

#[async_trait]
impl PulseTask for HeartbeatMdPulse {
    fn name(&self) -> &str {
        "heartbeat_md"
    }

    fn cadence(&self) -> PulseCadence {
        let minutes = self.interval_minutes.load(Ordering::Relaxed).max(5);
        PulseCadence::Every(Duration::from_secs(u64::from(minutes) * 60))
    }

    fn budget(&self) -> PulseBudget {
        // Generous: a tick may execute several agent turns. The cadence floor
        // is 5 minutes; a tick that exceeds 30 minutes is considered wedged.
        PulseBudget {
            max_duration: Duration::from_secs(30 * 60),
        }
    }

    async fn on_tick(&self, ctx: &PulseContext) -> Result<PulseOutcome> {
        {
            let mut m = self.metrics.lock();
            m.uptime_secs = ctx.started_at.elapsed().as_secs();
        }

        let report = crate::daemon::heartbeat_tick(
            &ctx.config,
            &self.engine,
            &self.metrics,
            self.delivery.as_ref(),
        )
        .await?;

        if ctx.config.heartbeat.adaptive {
            let failures = self.metrics.lock().consecutive_failures;
            let next = compute_adaptive_interval(
                ctx.config.heartbeat.interval_minutes.max(5),
                ctx.config.heartbeat.min_interval_minutes,
                ctx.config.heartbeat.max_interval_minutes,
                failures,
                report.has_high_priority,
            );
            self.interval_minutes.store(next, Ordering::Relaxed);
        }

        if report.tasks_run == 0 {
            Ok(PulseOutcome::Quiet)
        } else {
            Ok(PulseOutcome::Acted {
                summary: format!("executed {} heartbeat task(s)", report.tasks_run),
            })
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn pulse_with(config: &Config) -> HeartbeatMdPulse {
        HeartbeatMdPulse::new(config, Arc::new(crate::observability::NoopObserver)).unwrap()
    }

    #[test]
    fn pulse_name_is_stable_registry_key() {
        let config = Config::default();
        assert_eq!(pulse_with(&config).name(), "heartbeat_md");
    }

    #[test]
    fn cadence_follows_configured_interval_with_floor() {
        let mut config = Config::default();
        config.heartbeat.interval_minutes = 15;
        assert_eq!(
            pulse_with(&config).cadence(),
            PulseCadence::Every(Duration::from_secs(15 * 60))
        );

        // Sub-floor intervals clamp to 5 minutes, matching the legacy worker.
        config.heartbeat.interval_minutes = 1;
        assert_eq!(
            pulse_with(&config).cadence(),
            PulseCadence::Every(Duration::from_secs(5 * 60))
        );
    }

    #[test]
    fn construction_fails_on_invalid_delivery_config() {
        let mut config = Config::default();
        config.heartbeat.target = Some("telegram".into());
        // `to` missing — same explicit error as the legacy worker path.
        match HeartbeatMdPulse::new(&config, Arc::new(crate::observability::NoopObserver)) {
            Err(err) => assert!(err.to_string().contains("heartbeat.to is required")),
            Ok(_) => panic!("expected delivery validation error"),
        }
    }
}
