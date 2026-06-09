use super::event::{SensePriority, SensoryEvent};
use crate::config::SensesConfig;
use std::collections::{HashMap, VecDeque};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::time::Duration;
use tokio::sync::Notify;
use tokio::time::Instant;

/// What happens when a lane is at capacity.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OverflowPolicy {
    /// Apply backpressure: the producer waits for space. Used for P0/P1 so
    /// interrupts and direct messages are never lost (P1 blocking preserves
    /// the bounded-mpsc backpressure the bus replaces).
    Block,
    /// Ring-buffer semantics: evict the oldest event and count the drop.
    /// Used for P2/P3 telemetry where the newest reading wins.
    DropOldest,
}

const LANE_POLICIES: [OverflowPolicy; SensePriority::COUNT] = [
    OverflowPolicy::Block,      // Interrupt
    OverflowPolicy::Block,      // Direct
    OverflowPolicy::DropOldest, // Environmental
    OverflowPolicy::DropOldest, // Ambient
];

#[derive(Debug, thiserror::Error)]
pub enum PublishError {
    #[error("sensory bus is closed")]
    Closed,
}

struct Lane {
    queue: parking_lot::Mutex<VecDeque<SensoryEvent>>,
    capacity: usize,
    policy: OverflowPolicy,
    dropped: AtomicU64,
    /// Wakes one blocked producer when the consumer frees a slot.
    space: Notify,
}

struct PendingCoalesce {
    event: SensoryEvent,
    folds: u64,
    deadline: Instant,
}

struct BusInner {
    lanes: [Lane; SensePriority::COUNT],
    coalescer: parking_lot::Mutex<HashMap<String, PendingCoalesce>>,
    coalesce_window: Duration,
    starvation_credit: u32,
    /// Wakes the consumer on new events and on close.
    arrival: Notify,
    closed: AtomicBool,
    stale_dropped: AtomicU64,
}

/// Create a connected publisher/receiver pair. The bus is multi-producer,
/// single-consumer: `SensoryBus` is cheap to clone; `SensoryBusReceiver`
/// owns the drain state (starvation credits).
pub fn channel(config: &SensesConfig) -> (SensoryBus, SensoryBusReceiver) {
    let inner = Arc::new(BusInner {
        lanes: std::array::from_fn(|i| Lane {
            queue: parking_lot::Mutex::new(VecDeque::new()),
            capacity: config.capacity_for_lane(i),
            policy: LANE_POLICIES[i],
            dropped: AtomicU64::new(0),
            space: Notify::new(),
        }),
        coalescer: parking_lot::Mutex::new(HashMap::new()),
        coalesce_window: Duration::from_millis(config.coalesce_window_ms),
        starvation_credit: config.starvation_credit.max(1),
        arrival: Notify::new(),
        closed: AtomicBool::new(false),
        stale_dropped: AtomicU64::new(0),
    });
    (
        SensoryBus {
            inner: Arc::clone(&inner),
        },
        SensoryBusReceiver {
            inner,
            skipped: [0; SensePriority::COUNT],
        },
    )
}

/// Publisher handle.
#[derive(Clone)]
pub struct SensoryBus {
    inner: Arc<BusInner>,
}

impl SensoryBus {
    /// Publish an event into its priority lane.
    ///
    /// - `Environmental`/`Ambient` events with a `coalesce_key` fold into a
    ///   pending entry that flushes when the coalesce window elapses.
    /// - `Block` lanes await space (backpressure); `DropOldest` lanes evict
    ///   their oldest event and count the drop.
    pub async fn publish(&self, event: SensoryEvent) -> Result<(), PublishError> {
        if self.inner.closed.load(Ordering::Acquire) {
            return Err(PublishError::Closed);
        }

        let coalescable = event.priority >= SensePriority::Environmental
            && event.coalesce_key.is_some()
            && !self.inner.coalesce_window.is_zero();
        if coalescable {
            let key = event.coalesce_key.clone().unwrap_or_default();
            let mut pending = self.inner.coalescer.lock();
            if let Some(entry) = pending.get_mut(&key) {
                // Latest event wins; the fold count records what it absorbed.
                entry.folds += 1;
                entry.event = event;
                return Ok(());
            }
            pending.insert(
                key,
                PendingCoalesce {
                    event,
                    folds: 0,
                    deadline: Instant::now() + self.inner.coalesce_window,
                },
            );
            drop(pending);
            // Wake the consumer so it re-arms its flush deadline.
            self.inner.arrival.notify_one();
            return Ok(());
        }

        let mut event = event;
        let lane = &self.inner.lanes[event.priority.lane()];
        loop {
            event = {
                let mut queue = lane.queue.lock();
                if queue.len() < lane.capacity {
                    queue.push_back(event);
                    drop(queue);
                    self.inner.arrival.notify_one();
                    return Ok(());
                }
                match lane.policy {
                    OverflowPolicy::DropOldest => {
                        queue.pop_front();
                        lane.dropped.fetch_add(1, Ordering::Relaxed);
                        queue.push_back(event);
                        drop(queue);
                        self.inner.arrival.notify_one();
                        return Ok(());
                    }
                    // Fall through to wait for space, returning ownership.
                    OverflowPolicy::Block => event,
                }
            };
            lane.space.notified().await;
            if self.inner.closed.load(Ordering::Acquire) {
                return Err(PublishError::Closed);
            }
        }
    }

    /// Close the bus: publishers get `Closed`, blocked publishers wake, and
    /// the receiver drains remaining events (coalesced entries flush
    /// immediately) before yielding `None`.
    pub fn close(&self) {
        self.inner.closed.store(true, Ordering::Release);
        for lane in &self.inner.lanes {
            lane.space.notify_waiters();
        }
        self.inner.arrival.notify_waiters();
        self.inner.arrival.notify_one();
    }

    /// Total events evicted from the given lane by `DropOldest` overflow.
    pub fn dropped(&self, priority: SensePriority) -> u64 {
        self.inner.lanes[priority.lane()]
            .dropped
            .load(Ordering::Relaxed)
    }

    /// Total expired events discarded by the receiver.
    pub fn stale_dropped(&self) -> u64 {
        self.inner.stale_dropped.load(Ordering::Relaxed)
    }
}

/// Single consumer that drains lanes in strict priority order with an
/// anti-starvation guard: after `starvation_credit` consecutive serves that
/// bypass a non-empty lower lane, that lane is served once.
pub struct SensoryBusReceiver {
    inner: Arc<BusInner>,
    skipped: [u32; SensePriority::COUNT],
}

impl SensoryBusReceiver {
    /// Next event by priority, or `None` once the bus is closed and drained.
    pub async fn next(&mut self) -> Option<SensoryEvent> {
        loop {
            let closed = self.inner.closed.load(Ordering::Acquire);
            let next_flush = self.flush_due_coalesced(closed);
            if let Some(event) = self.pop_prioritized() {
                return Some(event);
            }
            if closed && self.all_empty() {
                return None;
            }
            match next_flush {
                Some(deadline) => {
                    tokio::select! {
                        () = self.inner.arrival.notified() => {}
                        () = tokio::time::sleep_until(deadline) => {}
                    }
                }
                None => self.inner.arrival.notified().await,
            }
        }
    }

    /// Move due coalesced entries into their lanes (all of them when the bus
    /// is closed). Returns the earliest remaining flush deadline.
    fn flush_due_coalesced(&self, force_all: bool) -> Option<Instant> {
        let now = Instant::now();
        let mut due = Vec::new();
        let mut earliest = None;
        {
            let mut pending = self.inner.coalescer.lock();
            pending.retain(|_, entry| {
                if force_all || entry.deadline <= now {
                    due.push((std::mem::replace(&mut entry.folds, 0), entry.event.clone()));
                    false
                } else {
                    earliest =
                        Some(earliest.map_or(entry.deadline, |e: Instant| e.min(entry.deadline)));
                    true
                }
            });
        }
        for (folds, mut event) in due {
            event.folds = folds;
            // Coalescing is restricted to DropOldest lanes (P2/P3), so this
            // push never needs to block.
            let lane = &self.inner.lanes[event.priority.lane()];
            let mut queue = lane.queue.lock();
            if queue.len() >= lane.capacity {
                queue.pop_front();
                lane.dropped.fetch_add(1, Ordering::Relaxed);
            }
            queue.push_back(event);
        }
        earliest
    }

    fn pop_prioritized(&mut self) -> Option<SensoryEvent> {
        loop {
            let occupied: Vec<usize> = (0..SensePriority::COUNT)
                .filter(|&i| !self.inner.lanes[i].queue.lock().is_empty())
                .collect();
            let starved = occupied
                .iter()
                .copied()
                .find(|&i| self.skipped[i] >= self.inner.starvation_credit);
            let chosen = starved.or_else(|| occupied.first().copied())?;

            for &i in &occupied {
                if i != chosen {
                    self.skipped[i] = self.skipped[i].saturating_add(1);
                }
            }
            self.skipped[chosen] = 0;

            let lane = &self.inner.lanes[chosen];
            // Single consumer: producers only add, so the lane may have grown
            // but cannot have emptied since the occupancy check.
            let event = lane.queue.lock().pop_front()?;
            lane.space.notify_one();

            if event.is_expired(chrono::Utc::now()) {
                self.inner.stale_dropped.fetch_add(1, Ordering::Relaxed);
                tracing::debug!(source = %event.source, "sensory event expired unprocessed");
                continue;
            }
            return Some(event);
        }
    }

    fn all_empty(&self) -> bool {
        self.inner
            .lanes
            .iter()
            .all(|lane| lane.queue.lock().is_empty())
            && self.inner.coalescer.lock().is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::senses::event::SensePayload;
    use chrono::Utc;

    fn config() -> SensesConfig {
        SensesConfig::default()
    }

    fn obs(source: &str, priority: SensePriority) -> SensoryEvent {
        SensoryEvent::new(
            source,
            priority,
            SensePayload::Observation {
                text: format!("observation from {source}"),
            },
        )
    }

    fn source_of(event: &SensoryEvent) -> &str {
        &event.source
    }

    #[tokio::test]
    async fn drains_in_priority_order() {
        let (bus, mut rx) = channel(&config());
        bus.publish(obs("ambient", SensePriority::Ambient))
            .await
            .unwrap();
        bus.publish(obs("env", SensePriority::Environmental))
            .await
            .unwrap();
        bus.publish(obs("direct", SensePriority::Direct))
            .await
            .unwrap();
        bus.publish(obs("interrupt", SensePriority::Interrupt))
            .await
            .unwrap();
        bus.close();

        let order: Vec<String> = [
            rx.next().await.unwrap(),
            rx.next().await.unwrap(),
            rx.next().await.unwrap(),
            rx.next().await.unwrap(),
        ]
        .iter()
        .map(|e| source_of(e).to_string())
        .collect();
        assert_eq!(order, ["interrupt", "direct", "env", "ambient"]);
        assert!(rx.next().await.is_none());
    }

    #[tokio::test]
    async fn ambient_lane_drops_oldest_on_overflow() {
        let mut cfg = config();
        cfg.lane_capacity = vec![8, 64, 256, 2];
        let (bus, mut rx) = channel(&cfg);

        bus.publish(obs("first", SensePriority::Ambient))
            .await
            .unwrap();
        bus.publish(obs("second", SensePriority::Ambient))
            .await
            .unwrap();
        bus.publish(obs("third", SensePriority::Ambient))
            .await
            .unwrap();

        assert_eq!(bus.dropped(SensePriority::Ambient), 1);
        bus.close();
        assert_eq!(source_of(&rx.next().await.unwrap()), "second");
        assert_eq!(source_of(&rx.next().await.unwrap()), "third");
        assert!(rx.next().await.is_none());
    }

    #[tokio::test(start_paused = true)]
    async fn interrupt_lane_blocks_publisher_until_space() {
        let mut cfg = config();
        cfg.lane_capacity = vec![1, 64, 256, 256];
        let (bus, mut rx) = channel(&cfg);

        bus.publish(obs("first", SensePriority::Interrupt))
            .await
            .unwrap();

        let blocked_bus = bus.clone();
        let blocked = tokio::spawn(async move {
            blocked_bus
                .publish(obs("second", SensePriority::Interrupt))
                .await
        });

        // The second publish must still be pending while the lane is full.
        tokio::time::sleep(Duration::from_secs(5)).await;
        assert!(!blocked.is_finished());

        // Consuming one event frees a slot and unblocks the producer.
        assert_eq!(source_of(&rx.next().await.unwrap()), "first");
        blocked.await.unwrap().unwrap();
        assert_eq!(source_of(&rx.next().await.unwrap()), "second");
    }

    #[tokio::test]
    async fn starvation_credit_eventually_serves_lower_lane() {
        let mut cfg = config();
        cfg.starvation_credit = 3;
        let (bus, mut rx) = channel(&cfg);

        bus.publish(obs("ambient", SensePriority::Ambient))
            .await
            .unwrap();
        for i in 0..6 {
            bus.publish(obs(&format!("direct{i}"), SensePriority::Direct))
                .await
                .unwrap();
        }
        bus.close();

        let mut order = Vec::new();
        while let Some(event) = rx.next().await {
            order.push(source_of(&event).to_string());
        }
        // The ambient event is served after `starvation_credit` bypasses,
        // not last.
        let ambient_pos = order.iter().position(|s| s == "ambient").unwrap();
        assert_eq!(ambient_pos, 3, "order was {order:?}");
    }

    #[tokio::test(start_paused = true)]
    async fn coalesces_same_key_events_within_window() {
        let (bus, mut rx) = channel(&config());

        for i in 0..5 {
            bus.publish(
                obs(&format!("reading{i}"), SensePriority::Ambient).with_coalesce_key("hw:temp"),
            )
            .await
            .unwrap();
        }

        // Nothing is deliverable until the coalesce window (2s) elapses.
        let event = rx.next().await.unwrap();
        assert_eq!(source_of(&event), "reading4", "latest event wins");
        assert_eq!(event.folds, 4);

        bus.close();
        assert!(rx.next().await.is_none());
    }

    #[tokio::test]
    async fn close_flushes_pending_coalesced_events() {
        let (bus, mut rx) = channel(&config());
        bus.publish(obs("pending", SensePriority::Environmental).with_coalesce_key("fs:papers"))
            .await
            .unwrap();
        bus.close();

        // Flushes immediately on close instead of waiting out the window.
        assert_eq!(source_of(&rx.next().await.unwrap()), "pending");
        assert!(rx.next().await.is_none());
    }

    #[tokio::test]
    async fn direct_priority_events_are_never_coalesced() {
        let (bus, mut rx) = channel(&config());
        bus.publish(obs("a", SensePriority::Direct).with_coalesce_key("same"))
            .await
            .unwrap();
        bus.publish(obs("b", SensePriority::Direct).with_coalesce_key("same"))
            .await
            .unwrap();
        bus.close();

        assert_eq!(source_of(&rx.next().await.unwrap()), "a");
        assert_eq!(source_of(&rx.next().await.unwrap()), "b");
        assert!(rx.next().await.is_none());
    }

    #[tokio::test]
    async fn expired_events_are_discarded() {
        let (bus, mut rx) = channel(&config());
        bus.publish(
            obs("stale", SensePriority::Ambient)
                .with_expiry(Utc::now() - chrono::Duration::seconds(10)),
        )
        .await
        .unwrap();
        bus.publish(obs("fresh", SensePriority::Ambient))
            .await
            .unwrap();
        bus.close();

        assert_eq!(source_of(&rx.next().await.unwrap()), "fresh");
        assert!(rx.next().await.is_none());
        assert_eq!(bus.stale_dropped(), 1);
    }

    #[tokio::test]
    async fn publish_after_close_is_rejected() {
        let (bus, _rx) = channel(&config());
        bus.close();
        assert!(matches!(
            bus.publish(obs("late", SensePriority::Direct)).await,
            Err(PublishError::Closed)
        ));
    }
}
