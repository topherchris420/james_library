use super::traits::{PulseContext, PulseOutcome, PulseTask};
use anyhow::Result;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::{Semaphore, mpsc};
use tokio::time::Instant;
use tokio_util::sync::CancellationToken;
use tracing::{debug, info, warn};

/// Retry delay when a due tick is deferred because all permits are taken.
const DEFER_RETRY: Duration = Duration::from_secs(5);
/// Failure back-off is capped at `period * 2^MAX_BACKOFF_SHIFT`.
const MAX_BACKOFF_SHIFT: u32 = 4;

/// Completion report sent from a spawned tick back to the driver loop.
struct TickReport {
    index: usize,
    success: bool,
    summary: Option<String>,
    duration: Duration,
}

/// Per-task scheduling state owned by the driver loop.
struct TaskSchedule {
    task: Arc<dyn PulseTask>,
    next_due: Instant,
    in_flight: bool,
    consecutive_failures: u32,
}

impl TaskSchedule {
    fn new(task: Arc<dyn PulseTask>) -> Self {
        let next_due = Instant::now() + task.cadence().period();
        Self {
            task,
            next_due,
            in_flight: false,
            consecutive_failures: 0,
        }
    }

    /// Compute the next due instant after a completed tick, applying
    /// exponential back-off on consecutive failures.
    fn reschedule(&mut self, now: Instant) {
        let period = self.task.cadence().period();
        let shift = self.consecutive_failures.min(MAX_BACKOFF_SHIFT);
        let delay = period.saturating_mul(1u32 << shift);
        self.next_due = now + delay;
    }
}

/// Drives all registered pulse tasks on their cadences with bounded
/// concurrency, per-tick budgets, and structured cancellation.
pub struct PulseDriver {
    tasks: Vec<Arc<dyn PulseTask>>,
    ctx: Arc<PulseContext>,
    permits: Arc<Semaphore>,
    shutdown: CancellationToken,
}

impl PulseDriver {
    pub fn new(
        tasks: Vec<Arc<dyn PulseTask>>,
        ctx: Arc<PulseContext>,
        max_concurrent: usize,
        shutdown: CancellationToken,
    ) -> Self {
        Self {
            tasks,
            ctx,
            permits: Arc::new(Semaphore::new(max_concurrent.max(1))),
            shutdown,
        }
    }

    /// Run until cancelled. With no registered tasks the driver parks idle so
    /// the supervising component does not spin on restarts.
    pub async fn run(self) -> Result<()> {
        if self.tasks.is_empty() {
            info!("pulse driver: no pulses registered; idling until shutdown");
            self.shutdown.cancelled().await;
            return Ok(());
        }

        let names: Vec<&str> = self.tasks.iter().map(|t| t.name()).collect();
        info!("pulse driver started: {}", names.join(", "));

        let (report_tx, mut report_rx) = mpsc::channel::<TickReport>(self.tasks.len().max(1));
        let mut schedules: Vec<TaskSchedule> = self
            .tasks
            .iter()
            .map(|t| TaskSchedule::new(Arc::clone(t)))
            .collect();

        loop {
            let next_due = schedules
                .iter()
                .filter(|s| !s.in_flight)
                .map(|s| s.next_due)
                .min();

            tokio::select! {
                biased;
                () = self.shutdown.cancelled() => {
                    info!("pulse driver: shutdown requested; abandoning in-flight ticks");
                    return Ok(());
                }
                Some(report) = report_rx.recv() => {
                    self.apply_report(&mut schedules, report);
                }
                () = sleep_until_opt(next_due) => {
                    self.dispatch_due(&mut schedules, &report_tx);
                }
            }
        }
    }

    fn apply_report(&self, schedules: &mut [TaskSchedule], report: TickReport) {
        let Some(sched) = schedules.get_mut(report.index) else {
            return;
        };
        sched.in_flight = false;
        if report.success {
            sched.consecutive_failures = 0;
            if let Some(summary) = &report.summary {
                info!(
                    "pulse '{}' acted in {:?}: {summary}",
                    sched.task.name(),
                    report.duration
                );
            } else {
                debug!(
                    "pulse '{}' quiet tick in {:?}",
                    sched.task.name(),
                    report.duration
                );
            }
        } else {
            sched.consecutive_failures = sched.consecutive_failures.saturating_add(1);
            warn!(
                "pulse '{}' failed ({} consecutive); backing off",
                sched.task.name(),
                sched.consecutive_failures
            );
        }
        sched.reschedule(Instant::now());
    }

    fn dispatch_due(&self, schedules: &mut [TaskSchedule], report_tx: &mpsc::Sender<TickReport>) {
        let now = Instant::now();
        for (index, sched) in schedules
            .iter_mut()
            .enumerate()
            .filter(|(_, s)| !s.in_flight && s.next_due <= now)
        {
            // Bounded concurrency: never queue unbounded work. A deferred
            // task stays due and retries shortly.
            let Ok(permit) = Arc::clone(&self.permits).try_acquire_owned() else {
                warn!(
                    "pulse '{}' deferred: concurrency saturated",
                    sched.task.name()
                );
                sched.next_due = now + DEFER_RETRY;
                continue;
            };

            sched.in_flight = true;
            let task = Arc::clone(&sched.task);
            let ctx = Arc::clone(&self.ctx);
            let budget = task.budget();
            let shutdown = self.shutdown.child_token();
            let report_tx = report_tx.clone();

            tokio::spawn(async move {
                let _permit = permit;
                let started = std::time::Instant::now();
                let result = tokio::select! {
                    biased;
                    () = shutdown.cancelled() => Err(anyhow::anyhow!("cancelled")),
                    r = tokio::time::timeout(budget.max_duration, task.on_tick(&ctx)) => {
                        match r {
                            Ok(inner) => inner,
                            Err(_) => Err(anyhow::anyhow!(
                                "pulse budget exceeded ({:?})",
                                budget.max_duration
                            )),
                        }
                    }
                };
                let duration = started.elapsed();
                let report = match result {
                    Ok(PulseOutcome::Quiet) => TickReport {
                        index,
                        success: true,
                        summary: None,
                        duration,
                    },
                    Ok(PulseOutcome::Acted { summary }) => TickReport {
                        index,
                        success: true,
                        summary: Some(summary),
                        duration,
                    },
                    Err(e) => {
                        ctx.observer
                            .record_event(&crate::observability::ObserverEvent::Error {
                                component: "autonomy".into(),
                                message: format!("pulse '{}': {e}", task.name()),
                            });
                        TickReport {
                            index,
                            success: false,
                            summary: None,
                            duration,
                        }
                    }
                };
                // Driver gone (shutdown) — nothing left to report to.
                let _ = report_tx.send(report).await;
            });
        }
    }
}

/// Sleep until the deadline, or forever when no task is schedulable (all
/// in-flight). The driver then wakes on tick reports or shutdown instead.
async fn sleep_until_opt(deadline: Option<Instant>) {
    match deadline {
        Some(d) => tokio::time::sleep_until(d).await,
        None => std::future::pending().await,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::autonomy::traits::{PulseBudget, PulseCadence};
    use async_trait::async_trait;
    use std::sync::atomic::{AtomicU32, Ordering};

    struct TestPulse {
        name: &'static str,
        period: Duration,
        tick_duration: Duration,
        budget: Duration,
        ticks: AtomicU32,
        fail: bool,
    }

    impl TestPulse {
        fn new(name: &'static str, period: Duration) -> Self {
            Self {
                name,
                period,
                tick_duration: Duration::ZERO,
                budget: Duration::from_secs(60),
                ticks: AtomicU32::new(0),
                fail: false,
            }
        }
    }

    #[async_trait]
    impl PulseTask for TestPulse {
        fn name(&self) -> &str {
            self.name
        }

        fn cadence(&self) -> PulseCadence {
            PulseCadence::Every(self.period)
        }

        fn budget(&self) -> PulseBudget {
            PulseBudget {
                max_duration: self.budget,
            }
        }

        async fn on_tick(&self, _ctx: &PulseContext) -> anyhow::Result<PulseOutcome> {
            self.ticks.fetch_add(1, Ordering::SeqCst);
            if !self.tick_duration.is_zero() {
                tokio::time::sleep(self.tick_duration).await;
            }
            if self.fail {
                anyhow::bail!("intentional test failure");
            }
            Ok(PulseOutcome::Quiet)
        }
    }

    fn test_ctx() -> Arc<PulseContext> {
        Arc::new(PulseContext {
            config: crate::config::Config::default(),
            observer: Arc::new(crate::observability::NoopObserver),
            started_at: std::time::Instant::now(),
        })
    }

    #[tokio::test(start_paused = true)]
    async fn driver_ticks_on_cadence() {
        let pulse = Arc::new(TestPulse::new("tick_counter", Duration::from_secs(10)));
        let shutdown = CancellationToken::new();
        let driver = PulseDriver::new(
            vec![Arc::clone(&pulse) as Arc<dyn PulseTask>],
            test_ctx(),
            2,
            shutdown.clone(),
        );
        let handle = tokio::spawn(driver.run());

        tokio::time::sleep(Duration::from_secs(35)).await;
        shutdown.cancel();
        handle.await.unwrap().unwrap();

        // Due at t=10, 20, 30 within the 35s window.
        assert_eq!(pulse.ticks.load(Ordering::SeqCst), 3);
    }

    #[tokio::test(start_paused = true)]
    async fn driver_applies_failure_backoff() {
        let mut p = TestPulse::new("always_fails", Duration::from_secs(10));
        p.fail = true;
        let pulse = Arc::new(p);
        let shutdown = CancellationToken::new();
        let driver = PulseDriver::new(
            vec![Arc::clone(&pulse) as Arc<dyn PulseTask>],
            test_ctx(),
            2,
            shutdown.clone(),
        );
        let handle = tokio::spawn(driver.run());

        // Without back-off there would be ~10 ticks in 100s. With doubling
        // back-off the failures run at t=10, 30 (+20), 70 (+40) within 100s.
        tokio::time::sleep(Duration::from_secs(100)).await;
        shutdown.cancel();
        handle.await.unwrap().unwrap();

        assert_eq!(pulse.ticks.load(Ordering::SeqCst), 3);
    }

    #[tokio::test(start_paused = true)]
    async fn driver_enforces_tick_budget() {
        let mut p = TestPulse::new("over_budget", Duration::from_secs(10));
        p.tick_duration = Duration::from_secs(120);
        p.budget = Duration::from_secs(1);
        let pulse = Arc::new(p);
        let shutdown = CancellationToken::new();
        let driver = PulseDriver::new(
            vec![Arc::clone(&pulse) as Arc<dyn PulseTask>],
            test_ctx(),
            2,
            shutdown.clone(),
        );
        let handle = tokio::spawn(driver.run());

        // First tick at t=10 is abandoned at t=11 (budget), counted as a
        // failure, and rescheduled with back-off at t=31.
        tokio::time::sleep(Duration::from_secs(35)).await;
        shutdown.cancel();
        handle.await.unwrap().unwrap();

        assert_eq!(pulse.ticks.load(Ordering::SeqCst), 2);
    }

    #[tokio::test(start_paused = true)]
    async fn driver_defers_when_concurrency_saturated() {
        let mut a = TestPulse::new("slow_a", Duration::from_secs(10));
        a.tick_duration = Duration::from_secs(8);
        let mut b = TestPulse::new("slow_b", Duration::from_secs(10));
        b.tick_duration = Duration::from_secs(8);
        let (a, b) = (Arc::new(a), Arc::new(b));

        let shutdown = CancellationToken::new();
        let driver = PulseDriver::new(
            vec![
                Arc::clone(&a) as Arc<dyn PulseTask>,
                Arc::clone(&b) as Arc<dyn PulseTask>,
            ],
            test_ctx(),
            1, // single permit: the second due task must defer, not drop
            shutdown.clone(),
        );
        let handle = tokio::spawn(driver.run());

        tokio::time::sleep(Duration::from_secs(60)).await;
        shutdown.cancel();
        handle.await.unwrap().unwrap();

        assert!(a.ticks.load(Ordering::SeqCst) >= 1);
        assert!(b.ticks.load(Ordering::SeqCst) >= 1);
    }

    #[tokio::test(start_paused = true)]
    async fn driver_idles_without_tasks_until_shutdown() {
        let shutdown = CancellationToken::new();
        let driver = PulseDriver::new(vec![], test_ctx(), 2, shutdown.clone());
        let handle = tokio::spawn(driver.run());

        tokio::time::sleep(Duration::from_secs(3600)).await;
        assert!(!handle.is_finished());

        shutdown.cancel();
        handle.await.unwrap().unwrap();
    }

    #[tokio::test(start_paused = true)]
    async fn shutdown_cancels_in_flight_tick() {
        let mut p = TestPulse::new("long_runner", Duration::from_secs(5));
        p.tick_duration = Duration::from_secs(3600);
        p.budget = Duration::from_secs(7200);
        let pulse = Arc::new(p);
        let shutdown = CancellationToken::new();
        let driver = PulseDriver::new(
            vec![Arc::clone(&pulse) as Arc<dyn PulseTask>],
            test_ctx(),
            2,
            shutdown.clone(),
        );
        let handle = tokio::spawn(driver.run());

        // Let the tick start, then shut down while it is mid-flight.
        tokio::time::sleep(Duration::from_secs(10)).await;
        assert_eq!(pulse.ticks.load(Ordering::SeqCst), 1);
        shutdown.cancel();
        handle.await.unwrap().unwrap();
    }
}
