# Autonomous Runtime Design — Heartbeat, Sensory Bus, Episodic Identity

> **Status:** Design proposal (not yet runtime contract). Date-stamped 2026-06-09.
> **Scope:** `src/autonomy/` (new), `src/senses/` (new), `src/heartbeat/`, `src/agent/loop_.rs`,
> `src/memory/`, `src/config/schema/`, Python orchestration (`stagnation_monitor.py`,
> `episodic_memory_ingestor.py`, new `autonomy_supervisor.py`).
> **Risk tier:** High (touches runtime loop and tool-permission surfaces when implemented).
> This document is the blueprint; implementation lands in phased PRs (see §10).

The goal is to move R.A.I.N. from a request/response chatbot to a continuously running
entity: it ticks on its own clock, perceives its environment through a unified
prioritized event bus, detects its own stagnation, and carries a persistent episodic
identity and behavioral state across sessions.

The design deliberately **reuses existing subsystems** instead of duplicating them:

| Existing primitive | File | Role in this design |
|---|---|---|
| `HeartbeatEngine` | `src/heartbeat/engine.rs` | Becomes one `PulseTask` among many under a generalized driver |
| Cron scheduler | `src/cron/scheduler.rs` | Long-horizon scheduled work; heartbeat handles sub-minute reflexes |
| Channel dispatch | `src/channels/dispatch.rs`, `listener.rs` | Pattern reused (supervised listeners, bounded mpsc, per-sender cancellation) and subsumed by the Sensory Bus |
| Loop detection | `src/agent/loop_.rs` (pacing-based identical-output check) | Extended into a full `VitalsMonitor` with intervention actions |
| `Memory` trait | `src/memory/traits.rs` (namespaces, `importance`, `superseded_by`) | Episodic layer is a namespace, not a new backend |
| `Observer` trait | `src/observability/traits.rs` (`HeartbeatTick` already exists) | Gains state-transition and vitals events |
| Python detectors | `stagnation_monitor.py`, `episodic_memory_ingestor.py` | Semantics ported to Rust for in-loop enforcement; Python remains the offline/graph-ingest tier |

---

## 0. System Overview

```text
                        ┌─────────────────────────────────────────────┐
                        │            AutonomousRuntime                │
                        │  (src/autonomy/runtime.rs — supervisor)     │
                        │                                             │
   Channels ─┐          │  ┌────────────┐   wake   ┌───────────────┐  │
   Peripherals├─ Sense ──┼─▶│ SensoryBus │─────────▶│ PulseDriver   │  │
   Gateway   ─┘ adapters │  │ (P0..P3    │  Notify  │ (tick loop +  │  │
   FS / TTY  ─┘          │  │  lanes)    │          │  PulseTasks)  │  │
                        │  └─────┬──────┘          └──────┬────────┘  │
                        │        │ drain                  │ tick      │
                        │        ▼                        ▼           │
                        │  ┌────────────────────────────────────┐     │
                        │  │ Agent turn (loop_.rs)              │     │
                        │  │  • AmbientContext injected         │     │
                        │  │  • VitalsMonitor per iteration     │     │
                        │  │  • BehavioralState gates tools/    │     │
                        │  │    pacing/tone                     │     │
                        │  └───────┬──────────────────┬─────────┘     │
                        │          ▼                  ▼               │
                        │   Memory (episodic ns)   Observer events    │
                        └──────────┼──────────────────────────────────┘
                                   ▼  JSONL contracts (schema_version)
                        Python tier: autonomy_supervisor.py
                        (episodic ingest → vector/graph, remediation,
                         offline consolidation, out-of-band alerting)
```

Three invariants hold everywhere below:

1. **The reasoning loop never blocks on perception.** Senses write into bounded lanes;
   the loop reads a snapshot.
2. **State may only narrow privileges, never widen them.** Behavioral states intersect
   with `SecurityPolicy`; there is no state that grants extra capability
   (secure-by-default, CLAUDE.md §3.6).
3. **Ambient context is ephemeral by construction.** Nothing enters permanent memory
   except through the episodic ingestor, which records provenance.

---

## 1. Pillar 1 — Continuous Autonomous Runtime (Heartbeat)

### 1.1 Why generalize `HeartbeatEngine`

Today `HeartbeatEngine::run()` is a single `tokio::time::interval` loop hard-coded to
parse `HEARTBEAT.md`. That is one *task*, not a *runtime*. The driver below owns the
clock and the supervision; concrete behaviors become `PulseTask` implementations,
following the same trait + factory pattern as `Provider`/`Channel`/`Tool`.

### 1.2 Trait boundary: `PulseTask`

```rust
// src/autonomy/traits.rs
use async_trait::async_trait;
use std::time::Duration;

/// When a pulse task wants to run.
#[derive(Debug, Clone)]
pub enum PulseCadence {
    /// Fixed wall-clock period (drift-corrected by the driver).
    Every(Duration),
    /// Run when the sensory bus delivers an event matching the filter,
    /// debounced by `min_gap` so event storms cannot starve other tasks.
    OnEvent { filter: EventFilter, min_gap: Duration },
    /// Both: periodic baseline plus event-driven early wake.
    Hybrid { every: Duration, filter: EventFilter, min_gap: Duration },
}

/// Hard resource ceiling for one tick of one task. Enforced by the driver,
/// not trusted to the task (fail-fast, CLAUDE.md §3.5).
#[derive(Debug, Clone, Copy)]
pub struct PulseBudget {
    pub max_duration: Duration,      // tokio::time::timeout around on_tick
    pub max_llm_calls: u32,          // 0 = pure introspection, no provider cost
    pub max_tool_calls: u32,
}

impl Default for PulseBudget {
    fn default() -> Self {
        Self { max_duration: Duration::from_secs(60), max_llm_calls: 0, max_tool_calls: 0 }
    }
}

#[derive(Debug, Clone)]
pub enum PulseOutcome {
    /// Nothing to do; driver records a quiet tick.
    Quiet,
    /// Work was performed; summary is logged and may be folded into ambient context.
    Acted { summary: String },
    /// Task requests a full agent turn (queued through the SensoryBus as a
    /// `SenseKind::SelfPrompt` event — pulses never call loop_.rs directly).
    RequestTurn { prompt: String, priority: SensePriority },
    /// Task detected a condition requiring escalation (deadman, vitals, budget).
    Escalate { alert: VitalsAlert },
}

#[async_trait]
pub trait PulseTask: Send + Sync {
    /// Stable, lowercase registry key (factory naming contract, CLAUDE.md §6.3).
    fn name(&self) -> &str;
    fn cadence(&self) -> PulseCadence;
    fn budget(&self) -> PulseBudget { PulseBudget::default() }

    /// One bounded unit of work. MUST be cancel-safe: the driver wraps this in
    /// `timeout` + a `CancellationToken` and will abandon the future on shutdown.
    async fn on_tick(&self, ctx: &PulseContext) -> anyhow::Result<PulseOutcome>;
}
```

`PulseContext` is the *read-mostly* capability surface handed to tasks. It exposes
snapshots and request queues — never `&mut Agent`:

```rust
// src/autonomy/context.rs
pub struct PulseContext {
    pub now: chrono::DateTime<chrono::Utc>,
    pub state: BehavioralStateSnapshot,            // §3.4 — read-only copy
    pub vitals: VitalsSnapshot,                    // §1.5
    pub ambient: AmbientContextHandle,             // §2.4 — append-only, TTL'd
    pub memory: std::sync::Arc<dyn crate::memory::Memory>,
    pub observer: std::sync::Arc<dyn crate::observability::Observer>,
    pub bus: SensoryBusHandle,                     // emit SelfPrompt / Escalate events
    pub workspace_dir: std::path::PathBuf,
}
```

Initial registered tasks (factory in `src/autonomy/mod.rs`, keys are config-facing):

| Key | Cadence | Budget | Behavior |
|---|---|---|---|
| `"heartbeat_md"` | `Every(interval_minutes)` | 1 LLM call (two-phase decision) | Wraps today's `HeartbeatEngine::collect_runnable_tasks` + decision prompt, emits `RequestTurn` per approved task |
| `"vitals"` | `Every(10s)` | 0 LLM calls | Samples RSS/token spend/queue depths into `VitalsSnapshot`; raises `Escalate` on threshold breach |
| `"task_reaper"` | `Every(30s)` | 0 | Audits in-flight per-sender tasks (dispatch.rs registry) for overdue cancellation tokens |
| `"memory_hygiene"` | `Every(6h)` | 0–1 | Triggers `memory::consolidation` + `hygiene` passes when idle |
| `"deadman"` | `Every(60s)` | 0 | Existing dead-man's-switch semantics from `HeartbeatConfig`, escalates to out-of-band channel |

### 1.3 The driver loop (tokio construct)

One driver task owns all cadences. Key properties: drift-corrected intervals,
`MissedTickBehavior::Skip` (a slow tick must not cause a burst of catch-up ticks),
bounded concurrency, biased shutdown, and event-driven early wake from the bus.

```rust
// src/autonomy/driver.rs
use tokio::time::{interval_at, Instant, MissedTickBehavior};
use tokio_util::sync::CancellationToken;

pub struct PulseDriver {
    tasks: Vec<std::sync::Arc<dyn PulseTask>>,
    ctx: std::sync::Arc<PulseContext>,
    wake: std::sync::Arc<tokio::sync::Notify>,   // pinged by SensoryBus on P0/P1 arrival
    permits: std::sync::Arc<tokio::sync::Semaphore>, // max concurrent ticks (default 2)
    shutdown: CancellationToken,
}

impl PulseDriver {
    pub async fn run(self) -> anyhow::Result<()> {
        // Per-task interval state. Smallest period defines the base resolution.
        let mut schedules: Vec<TaskSchedule> = self
            .tasks
            .iter()
            .map(|t| TaskSchedule::new(t.clone()))
            .collect();

        let base = schedules
            .iter()
            .filter_map(|s| s.period())
            .min()
            .unwrap_or(std::time::Duration::from_secs(10));

        let mut clock = interval_at(Instant::now() + base, base);
        clock.set_missed_tick_behavior(MissedTickBehavior::Skip);

        loop {
            tokio::select! {
                // Shutdown wins over everything: drain nothing, cancel children.
                biased;
                _ = self.shutdown.cancelled() => {
                    tracing::info!("pulse driver: shutdown, cancelling in-flight ticks");
                    return Ok(());
                }
                // Early wake: a high-priority sensory event arrived. Event-cadenced
                // tasks get a chance to run *now* instead of at next clock edge.
                _ = self.wake.notified() => {
                    self.dispatch_due(&mut schedules, /*event_wake=*/true).await;
                }
                _ = clock.tick() => {
                    self.dispatch_due(&mut schedules, /*event_wake=*/false).await;
                }
            }
        }
    }

    async fn dispatch_due(&self, schedules: &mut [TaskSchedule], event_wake: bool) {
        let now = Instant::now();
        for sched in schedules.iter_mut().filter(|s| s.is_due(now, event_wake)) {
            // Bounded concurrency: if all permits are taken, the task stays due
            // and runs on the next edge — we never queue unbounded work.
            let Ok(permit) = self.permits.clone().try_acquire_owned() else {
                self.ctx.observer.record_event(&crate::observability::ObserverEvent::Error {
                    component: "autonomy".into(),
                    message: format!("pulse '{}' deferred: concurrency saturated", sched.name()),
                });
                continue;
            };
            sched.mark_started(now);

            let task = sched.task();
            let ctx = self.ctx.clone();
            let budget = task.budget();
            let shutdown = self.shutdown.child_token();

            tokio::spawn(async move {
                let _permit = permit; // released on drop
                let started = std::time::Instant::now();
                let result = tokio::select! {
                    biased;
                    _ = shutdown.cancelled() => Err(anyhow::anyhow!("cancelled")),
                    r = tokio::time::timeout(budget.max_duration, task.on_tick(&ctx)) => {
                        r.map_err(|_| anyhow::anyhow!("budget exceeded: {:?}", budget.max_duration))
                          .and_then(|inner| inner)
                    }
                };
                let elapsed = started.elapsed();
                match result {
                    Ok(outcome) => ctx.handle_outcome(task.name(), outcome, elapsed).await,
                    Err(e) => ctx.record_pulse_failure(task.name(), &e, elapsed),
                }
            });
        }
    }
}
```

Notes that matter in production:

- **`try_acquire_owned`, not `acquire`** — the driver loop itself must never park on a
  semaphore; deferral is explicit and observable.
- **Cancellation is structural.** Every tick future is a child token of the runtime
  token; `rain stop` cancels the driver, which cancels all ticks. Tasks holding
  external resources implement `Drop`-safe cleanup (same discipline as channel
  listeners).
- **`handle_outcome` is the only bridge to the agent.** `RequestTurn` becomes a
  `SensoryEvent { kind: SelfPrompt, .. }` on the bus, so self-initiated work flows
  through exactly the same prioritization, dedup, and dispatch path as a Telegram
  message. There is no privileged back door into `loop_.rs`.

Adaptive pacing reuses the existing `compute_adaptive_interval` (engine.rs:144):
`TaskSchedule::is_due` consults consecutive-failure counts and high-priority task
presence the same way, so the back-off semantics users already rely on are preserved.

### 1.4 Wiring into the process

`AutonomousRuntime::spawn(config, deps) -> AutonomyHandle` is started by the same
entry path that today spawns `HeartbeatEngine::run()` and the channel listeners
(`src/channels/startup.rs`). The handle exposes:

```rust
pub struct AutonomyHandle {
    pub shutdown: CancellationToken,
    pub vitals: tokio::sync::watch::Receiver<VitalsSnapshot>,
    pub state: tokio::sync::watch::Receiver<BehavioralStateSnapshot>,
}
```

`watch` channels (latest-value semantics) are deliberate: consumers like the gateway
`/health` endpoint and the dispatch loop need *current* vitals, never a backlog.

### 1.5 Stagnation & vitals monitor (in-loop enforcement)

`stagnation_monitor.py` already defines the right detectors (dead-end: N consecutive
near-duplicate responses via similarity ≥ 0.95; stagnation: novelty window with low
mean + low variance). Those semantics are ported to Rust so they run *inside*
`run_tool_call_loop_with_policy` where they can actually intervene, while the Python
monitor remains for offline/lab analysis.

```rust
// src/autonomy/vitals.rs
pub struct VitalsThresholds {
    pub dead_end_window: usize,        // default 3
    pub dead_end_similarity: f64,      // default 0.95 (trigram Jaccard — no new deps)
    pub stagnation_window: usize,      // default 5
    pub stagnation_novelty_mean: f64,  // default 0.15
    pub stagnation_novelty_var: f64,   // default 0.01
    pub max_rss_bytes: Option<u64>,    // memory budget
    pub max_turn_tokens: Option<u64>,  // spend budget per turn
}

#[derive(Debug, Clone, serde::Serialize)]
pub enum VitalsVerdict {
    Healthy,
    DeadEnd { similarity: f64 },
    Stagnant { novelty_mean: f64 },
    BudgetExceeded { resource: &'static str, used: u64, limit: u64 },
}

#[derive(Debug, Clone)]
pub enum Intervention {
    /// Inject a course-correction message into history and continue.
    Redirect { prompt: String },
    /// End the turn now with a partial answer; schedule a consolidation pulse.
    YieldAndConsolidate,
    /// End the turn, transition BehavioralState -> Alert, deliver out-of-band
    /// notification via the configured heartbeat/deadman channel.
    AlertOutOfBand { reason: String },
}

pub struct VitalsMonitor { /* ring buffers over recent assistant outputs + counters */ }

impl VitalsMonitor {
    /// Called once per loop iteration in run_tool_call_loop_with_policy, in the
    /// same place the existing pacing-based identical-output check runs today.
    pub fn observe_iteration(
        &mut self,
        assistant_text: &str,
        tokens_this_turn: u64,
    ) -> VitalsVerdict { /* sliding-window novelty + budget checks */ }

    pub fn intervention_for(&self, verdict: &VitalsVerdict, escalations: u32) -> Intervention {
        match (verdict, escalations) {
            (VitalsVerdict::DeadEnd { .. }, 0) => Intervention::Redirect {
                prompt: DEAD_END_REDIRECT_PROMPT.into(), // mirrors MonitorVerdict.intervention_prompt
            },
            (VitalsVerdict::DeadEnd { .. }, _) => Intervention::YieldAndConsolidate,
            (VitalsVerdict::Stagnant { .. }, 0..=1) => Intervention::YieldAndConsolidate,
            (VitalsVerdict::BudgetExceeded { .. }, _) | (_, 2..) => Intervention::AlertOutOfBand {
                reason: format!("{verdict:?}"),
            },
            _ => Intervention::Redirect { prompt: STAGNATION_NUDGE_PROMPT.into() },
        }
    }
}
```

Integration point: `loop_.rs` already exits on identical-output detection when
`pacing.loop_detection_min_elapsed_secs` is set. The monitor replaces that ad-hoc
check with a graded ladder — redirect → yield+consolidate → out-of-band alert — and
each escalation emits `ObserverEvent::VitalsIntervention` (§8) and appends a
`vitals` record to the runtime JSONL stream (§4) so the Python tier sees it.

`YieldAndConsolidate` does two concrete things: (a) returns the best partial answer
with an explicit `[yielded: stagnation]` marker rather than silently truncating
(fail-fast, no fake success), and (b) enqueues the `memory_hygiene` pulse with an
immediate deadline so `memory::consolidation` runs while the agent is quiescent.

---

## 2. Pillar 2 — Real-Time Environment Perception (Sensory Bus)

### 2.1 Event envelope (the cross-language data contract)

One envelope for everything: channel messages, terminal interrupts, file attachments,
webhooks, hardware signals, and the runtime's own self-prompts. Serde model is the
canonical schema; Python mirrors it in §4.

```rust
// src/senses/event.rs
use serde::{Deserialize, Serialize};

pub const SENSORY_SCHEMA_VERSION: u32 = 1;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum SensePriority {
    /// P0 — interrupts: operator /stop, deadman trip, hardware fault line.
    Interrupt = 0,
    /// P1 — direct address: user messages, paired-device commands.
    Direct = 1,
    /// P2 — environmental: webhooks, file changes, sensor threshold crossings.
    Environmental = 2,
    /// P3 — ambient telemetry: periodic sensor readings, presence signals.
    Ambient = 3,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum SensePayload {
    /// Wraps the existing ChannelMessage verbatim — channels keep their schema.
    ChannelMessage(crate::channels::traits::ChannelMessage),
    TerminalInterrupt { signal: String },                       // "SIGINT", "/stop"
    Attachment { media_ref: String, mime: String, origin: String },
    WebhookDelivery { route: String, body_digest: String },     // body stored out-of-band
    HardwareSignal { peripheral: String, line: String, value: serde_json::Value },
    ResourcePressure { resource: String, used: u64, limit: u64 },
    /// A pulse task asking for an agent turn (§1.3).
    SelfPrompt { task: String, prompt: String },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SensoryEvent {
    pub schema_version: u32,            // = SENSORY_SCHEMA_VERSION
    pub id: String,                     // uuid v7 (time-ordered)
    pub source: String,                 // "channel:telegram", "peripheral:nucleo-f401re-0",
                                        // "gateway:webhook", "autonomy:heartbeat_md"
    pub priority: SensePriority,
    pub observed_at: chrono::DateTime<chrono::Utc>,
    /// After this instant the event is stale and may be dropped unprocessed.
    pub expires_at: Option<chrono::DateTime<chrono::Utc>>,
    /// Events sharing a key within a debounce window are coalesced (latest wins,
    /// count recorded). E.g. "hw:nucleo:temp" or "fs:papers/".
    pub coalesce_key: Option<String>,
    pub payload: SensePayload,
}
```

Security note: payloads from channels/webhooks are **untrusted input**. The bus does
no interpretation — sanitization stays where it lives today (`channels/sanitize.rs`,
gateway validation). The envelope adds routing metadata only; secrets and raw webhook
bodies are referenced by digest, never embedded (no-secrets-in-logs, CLAUDE.md §3.6).

### 2.2 Trait boundary: `Sense`

Deliberately isomorphic to `Channel::listen` so every existing channel adapts with a
ten-line shim, and the supervised-listener machinery (`listener.rs`: exponential
backoff, health heartbeat) is reused unchanged:

```rust
// src/senses/traits.rs
#[async_trait::async_trait]
pub trait Sense: Send + Sync {
    fn name(&self) -> &str;                      // "telegram", "gpio", "fswatch"
    fn default_priority(&self) -> SensePriority;

    /// Long-running producer. Push events into `tx`; return Err to trigger
    /// supervised restart with backoff (same contract as Channel::listen).
    async fn sense(
        &self,
        tx: tokio::sync::mpsc::Sender<SensoryEvent>,
    ) -> anyhow::Result<()>;

    async fn health_check(&self) -> bool { true }
}
```

Built-in adapters registered through a `src/senses/factory.rs` (keys: `"channels"`,
`"peripherals"`, `"terminal"`, `"fswatch"`, `"gateway"`):

- **`ChannelSense`** wraps the existing fan-in `mpsc::Sender<ChannelMessage>`: each
  message becomes `SensePayload::ChannelMessage` at `Direct` priority (`/stop`
  upgraded to `Interrupt`, matching dispatch.rs's stop-command detection).
- **`PeripheralSense`** polls/subscribes `Peripheral` boards. GPIO edge interrupts map
  to `Environmental`; periodic sensor sweeps to `Ambient` with a `coalesce_key` per
  line so a chatty sensor folds into one event per window.
- **`TerminalSense`** turns SIGINT/readline interrupts into `Interrupt`.
- **`FsWatchSense`** (notify-style watcher over configured paths, e.g. `papers/`,
  `HEARTBEAT.md`) emits `Environmental` with per-directory coalescing.

### 2.3 Broker: prioritized, bounded, non-blocking

Four bounded lanes, one drain task, strict priority with anti-starvation credits.

```rust
// src/senses/bus.rs
pub struct LanePolicy {
    pub capacity: usize,
    pub on_full: OverflowPolicy,
}

pub enum OverflowPolicy {
    /// P0 only: apply backpressure to the producer (an interrupt must never drop).
    Block,
    /// P1: reject-newest with an explicit error back to the channel (visible failure
    /// beats silent loss for direct user messages).
    RejectNewest,
    /// P2/P3: ring-buffer semantics — evict oldest, increment `dropped` counter,
    /// spill a digest line to runtime JSONL (§4) for the Python tier.
    DropOldest,
}

pub struct SensoryBus {
    lanes: [Lane; 4],                       // index = SensePriority as usize
    coalescer: CoalesceMap,                 // key -> (latest event, fold count, deadline)
    wake: std::sync::Arc<tokio::sync::Notify>, // shared with PulseDriver (§1.3)
}

impl SensoryBus {
    /// Producer-side: route by priority, coalesce, never block (except P0 Block).
    pub async fn publish(&self, event: SensoryEvent) -> Result<(), PublishError> { /* … */ }

    /// Consumer-side drain with starvation guard: strict priority, but after
    /// `starvation_credit` consecutive higher-lane events, one lower-lane event
    /// is serviced. Defaults: capacity [8, 64, 256, 256], credit 16.
    pub async fn next(&mut self) -> SensoryEvent {
        loop {
            tokio::select! {
                biased;                              // priority order is the point
                Some(e) = self.lanes[0].recv() => return e,
                Some(e) = self.lanes[1].recv(), if self.credit_ok(1) => return e,
                Some(e) = self.lanes[2].recv(), if self.credit_ok(2) => return e,
                Some(e) = self.lanes[3].recv(), if self.credit_ok(3) => return e,
                _ = self.coalescer.next_deadline() => { self.coalescer.flush_due().await; }
            }
        }
    }
}
```

The drain task replaces today's single `mpsc::Receiver<ChannelMessage>` head of
`run_message_dispatch_loop`. Routing after `next()`:

- `Interrupt` → existing per-sender cancellation registry (dispatch.rs) fires
  immediately; the bus also pings `wake` so the `task_reaper` pulse audits state.
- `Direct` and `SelfPrompt` → agent-turn dispatch, same semaphore-bounded path as
  today (`max_in_flight_messages` unchanged).
- `Environmental` / `Ambient` → **do not start turns**. They fold into the
  `AmbientContextBuffer` (§2.4) and optionally match `PulseCadence::OnEvent` filters.
  This is the load-bearing decision that keeps the reasoning loop unflooded: ambient
  reality changes what the agent *knows*, not how often it *speaks*.

### 2.4 Contextual awareness injection (ephemeral by construction)

```rust
// src/senses/ambient.rs
pub struct AmbientFact {
    pub source: String,
    pub text: String,                   // one-line, pre-sanitized rendering
    pub observed_at: chrono::DateTime<chrono::Utc>,
    pub expires_at: chrono::DateTime<chrono::Utc>,  // TTL mandatory — no immortal facts
    pub fold_count: u32,                // how many raw events coalesced into this line
}

/// Fixed-capacity ring (default 32 facts, ~1k token render budget).
pub struct AmbientContextBuffer { /* ring + token-budget renderer */ }

impl AmbientContextBuffer {
    pub fn upsert(&mut self, key: &str, fact: AmbientFact);
    /// Called by SystemPromptBuilder at each turn start. Expired facts are pruned
    /// first; render is deterministic (sorted by recency) for reproducible prompts.
    pub fn render(&mut self, token_budget: usize) -> Option<String>;
}
```

Render shape, injected by `SystemPromptBuilder` as its own delimited section:

```text
## Environment (ephemeral — observations expire; do not store as facts)
- [12:04:31Z] peripheral:nucleo-0 temp_c=41.2 (×12 readings)
- [12:03:58Z] fswatch papers/ 3 files changed
- [11:58:02Z] channel:telegram operator last seen
```

Guarantees against knowledge-graph pollution:

1. The buffer never touches the `Memory` trait. It lives in RAM, dies with the
   process, and is excluded from `auto_save` history persistence.
2. The section header carries an explicit instruction not to memorize, and the
   memory tools' write path tags any entry whose content matches an active ambient
   line with `namespace: "ambient_echo"` so hygiene passes can prune model-initiated
   leakage.
3. **Promotion is exclusive to the episodic ingestor**: when an episode closes (§3.3),
   the ambient facts active during that episode are summarized into the episode
   record with `provenance: "ambient"` — a deliberate, attributable, single doorway
   from perception into permanent memory.

---

## 3. Pillar 3 — Persistent Identity & Interaction Memory

### 3.1 Layering model

| Layer | Backing | Lifetime | Examples |
|---|---|---|---|
| Ambient | RAM ring (§2.4) | seconds–minutes (TTL) | sensor lines, presence |
| Episodic | `Memory` namespace `"episodic"` + JSONL + vector index | weeks–months, decaying `importance` | "the 06-08 debugging session", affect traces |
| Semantic | existing `MemoryCategory::Core` | indefinite | preferences, facts, decisions |
| Procedural | existing `store_procedural` | indefinite | how-to traces |

Episodes are the bridge: raw events are grouped, summarized, affect-scored, embedded,
and indexed; the raw event stream itself stays in append-only JSONL (cheap, greppable,
replayable) rather than bloating the vector store.

### 3.2 Cross-language episode contracts

The existing Python `EpisodicEvent` (`episodic_memory_ingestor.py`: `timestamp`,
`agent_name`, `tool`, `args`, `sentence`, `duration_ms`) is kept **back-compatible**:
v2 only adds optional fields, so the current JSONL tailer keeps working.

**Rust (canonical, `src/autonomy/episodic.rs`):**

```rust
pub const EPISODIC_SCHEMA_VERSION: u32 = 2;

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct EpisodicEventV2 {
    // ── v1 fields (unchanged, required) ─────────────────────────
    pub timestamp: String,                       // RFC 3339
    pub agent_name: String,                      // R.A.I.N.-scoped label only
    pub tool: String,
    pub args: serde_json::Value,
    pub sentence: String,                        // one-line natural-language rendering
    pub duration_ms: u64,
    // ── v2 additions (all optional ⇒ v1 lines still parse) ─────
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub schema_version: Option<u32>,             // Some(2) for new writers
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub episode_id: Option<String>,              // assigned at segmentation time
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub session_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub channel: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub state: Option<BehavioralState>,          // state at event time (§3.4)
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub outcome: Option<EventOutcome>,           // success | failure | intervened
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct Episode {
    pub schema_version: u32,                     // 2
    pub id: String,                              // "ep-" + uuid v7
    pub started_at: String,                      // RFC 3339
    pub ended_at: String,
    pub session_id: Option<String>,
    pub channel: Option<String>,
    pub event_count: u32,
    /// LLM- or heuristic-generated 2–4 sentence narrative summary.
    pub summary: String,
    /// Behavioral/affect trace for alignment retrieval.
    pub affect: AffectTrace,
    /// 0.0–1.0; maps directly onto MemoryEntry.importance for ranking + decay.
    pub salience: f64,
    /// States visited, in order, with durations (ms).
    pub state_trace: Vec<(BehavioralState, u64)>,
    /// Ambient facts promoted at close (§2.4), provenance-tagged.
    pub ambient_digest: Vec<String>,
    /// Vitals interventions that occurred (dead ends, yields, alerts).
    pub interventions: Vec<String>,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct AffectTrace {
    /// −1.0 (frustrated/failing) … +1.0 (succeeding/aligned). Derived from
    /// outcome ratios, intervention counts, and user-feedback signals.
    pub valence: f64,
    /// 0.0 (calm/idle) … 1.0 (alert/remediating). Derived from state_trace.
    pub arousal: f64,
    /// Dominant tags, e.g. ["debugging", "user_frustration", "recovered"].
    pub tags: Vec<String>,
}
```

**Python (mirror, `python/rain_contracts/episodic.py` — stdlib only):**

```python
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from enum import Enum
import json

EPISODIC_SCHEMA_VERSION = 2

class BehavioralState(str, Enum):
    IDLE = "idle"
    THINKING = "thinking"
    ALERT = "alert"
    REMEDIATING = "remediating"

@dataclass(slots=True)
class EpisodicEventV2:
    # v1 fields (wire-compatible with episodic_memory_ingestor.EpisodicEvent)
    timestamp: str
    agent_name: str
    tool: str
    args: dict
    sentence: str
    duration_ms: int
    # v2 optional additions
    schema_version: int | None = None
    episode_id: str | None = None
    session_id: str | None = None
    channel: str | None = None
    state: BehavioralState | None = None
    outcome: str | None = None          # "success" | "failure" | "intervened"

    def to_jsonl(self) -> str:
        d = {k: v for k, v in asdict(self).items() if v is not None}
        if isinstance(d.get("state"), BehavioralState):
            d["state"] = d["state"].value
        return json.dumps(d, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_jsonl(cls, line: str) -> "EpisodicEventV2":
        raw = json.loads(line)
        if "state" in raw and raw["state"] is not None:
            raw["state"] = BehavioralState(raw["state"])
        known = {f for f in cls.__dataclass_fields__}          # forward-compat:
        return cls(**{k: v for k, v in raw.items() if k in known})  # ignore unknown keys

@dataclass(slots=True)
class AffectTrace:
    valence: float = 0.0
    arousal: float = 0.0
    tags: list[str] = field(default_factory=list)

@dataclass(slots=True)
class Episode:
    schema_version: int
    id: str
    started_at: str
    ended_at: str
    event_count: int
    summary: str
    affect: AffectTrace
    salience: float
    state_trace: list[tuple[str, int]] = field(default_factory=list)
    ambient_digest: list[str] = field(default_factory=list)
    interventions: list[str] = field(default_factory=list)
    session_id: str | None = None
    channel: str | None = None
```

**Parsing rule (both sides):** unknown keys are ignored, missing optional keys default
to `None`/`Option::None`. This is the forward/backward compatibility contract; bump
`schema_version` only when a *required* field changes meaning.

### 3.3 Episode segmentation & ingestion pipeline

The Rust side **writes events**; the Python `EpisodicMemoryIngestor` (already tailing
`episodic_memory/episodic_events.jsonl`) **segments and indexes**. Segmentation
closes an episode when any boundary fires:

1. **Temporal gap** — no events for `gap_minutes` (default 20).
2. **Session boundary** — `session_id`/`channel` changes.
3. **State boundary** — transition into or out of `Alert`/`Remediating` (an incident
   is always its own episode; this is what makes "remember the last time this
   sensor tripped" retrievable as a unit).
4. **Topic drift** — embedding cosine between rolling event-sentence centroids drops
   below `drift_threshold` (default 0.55); only evaluated when embeddings are
   configured, otherwise rules 1–3 suffice (no heavy dependency added — CLAUDE.md §10).

On close, the ingestor: builds the `Episode` record → writes it to
`episodic_memory/episodes.jsonl` → indexes `summary` (+ affect tags) into the vector
store under namespace `episodic` → mirrors a compact form into the Rust `Memory`
backend via the existing CLI/gateway memory API:

```text
Memory::store(
    key      = episode.id,
    content  = episode.summary + affect tags,
    category = MemoryCategory::Custom("episodic"),
    session  = episode.session_id,
)            // importance := episode.salience
```

Retrieval at turn time uses the already-existing
`recall_namespaced("episodic", query, k, …)`: the prompt builder asks for the top-k
episodes whose summaries match the current context, giving the agent "I remember
when…" continuity, and the affect trace lets the state machine bias tone ("last
three episodes touching this subsystem ended valence-negative → open in cautious
register").

Salience decay is handled by the existing hygiene pass: a `memory_hygiene` pulse
(§1.2) multiplies `importance` by `decay_factor^age_weeks` and prunes below-floor
episodes, while `superseded_by` chains let consolidation merge near-duplicate
episodes without losing lineage.

### 3.4 Behavioral state machine

```rust
// src/autonomy/state.rs
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum BehavioralState {
    /// Quiescent: listening, ambient folding, low-cost pulses only.
    Idle,
    /// Actively executing a turn or self-prompted task.
    Thinking,
    /// Vitals breach / interrupt / hardware fault observed. Defensive posture.
    Alert,
    /// Executing a recovery plan (consolidation, remediation queue, restarts).
    Remediating,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct BehavioralStateSnapshot {
    pub state: BehavioralState,
    pub since: chrono::DateTime<chrono::Utc>,
    pub cause: String,                  // last transition trigger, for observability
    pub stress: f64,                    // 0.0–1.0 rolling vitals pressure
}
```

**Transition table** (anything not listed is rejected with an explicit error —
no silent transitions, CLAUDE.md §3.5):

| From | Trigger | To |
|---|---|---|
| Idle | `Direct`/`SelfPrompt` event dispatched | Thinking |
| Thinking | turn completes, vitals healthy | Idle |
| Thinking | `VitalsVerdict::{DeadEnd,Stagnant,BudgetExceeded}` (escalated) | Alert |
| Any | `SensePriority::Interrupt` event | Alert |
| Alert | remediation plan selected (consolidate / reap / restart listener) | Remediating |
| Alert | operator acknowledges via out-of-band channel | Idle |
| Remediating | plan succeeds, vitals healthy for `cooldown_secs` | Idle |
| Remediating | plan fails `max_remediation_attempts` times | Alert (re-escalate, dead-man notify) |

The Alert↔Remediating loop is bounded by `max_remediation_attempts` (default 3);
exhaustion stops automatic action and waits for an operator — the system must not
thrash itself "alive".

**Effects: `StatePolicy` (consulted at turn start and tool-resolution time):**

```rust
pub struct StatePolicy {
    /// Appended to the system prompt: tone/register modifier.
    pub tone_directive: &'static str,
    /// Multiplier over PacingConfig delays (Alert thinks slower & checks more).
    pub pacing_factor: f64,
    /// Tool gate, applied as INTERSECTION with SecurityPolicy & per-channel
    /// allowlists. States can only remove capability, never add it.
    pub tool_gate: ToolGate,
    pub max_tool_iterations_factor: f64,
}

pub enum ToolGate {
    All,                                   // Idle, Thinking: defer to SecurityPolicy
    DenyTags(&'static [&'static str]),     // Alert: deny ["destructive", "external_write"]
    AllowOnly(&'static [&'static str]),    // Remediating: ["memory_*", "shell_readonly",
                                           //  "health_*", "peripheral_read"]
}

pub fn policy_for(state: BehavioralState) -> StatePolicy {
    match state {
        BehavioralState::Idle => StatePolicy {
            tone_directive: "Calm, brief, ambient awareness.",
            pacing_factor: 1.0, tool_gate: ToolGate::All,
            max_tool_iterations_factor: 1.0,
        },
        BehavioralState::Thinking => StatePolicy {
            tone_directive: "Focused and thorough.",
            pacing_factor: 1.0, tool_gate: ToolGate::All,
            max_tool_iterations_factor: 1.0,
        },
        BehavioralState::Alert => StatePolicy {
            tone_directive: "Terse, factual, safety-first. State what is wrong, \
                             what you verified, and what you will NOT do automatically.",
            pacing_factor: 1.5,
            tool_gate: ToolGate::DenyTags(&["destructive", "external_write"]),
            max_tool_iterations_factor: 0.5,
        },
        BehavioralState::Remediating => StatePolicy {
            tone_directive: "Methodical recovery mode: one step, verify, report.",
            pacing_factor: 1.25,
            tool_gate: ToolGate::AllowOnly(&[
                "memory_consolidate", "memory_recall", "health_check",
                "shell_readonly", "peripheral_read",
            ]),
            max_tool_iterations_factor: 0.75,
        },
    }
}
```

Enforcement point: `tool_resolution.rs`/`tool_filter.rs` already filter the tool
registry per turn; the gate is one more intersection applied there, and the existing
`autonomy_level: AutonomyLevel` on `Agent` remains the outer bound.

**Persistence & identity continuity:** every transition appends a snapshot line to
`runtime/state_snapshots.jsonl` (§4) and stores the latest snapshot via
`Memory::store(key = "behavioral_state:current", …, MemoryCategory::Custom("autonomy"))`.
On boot, the runtime restores the last state; if it wakes into `Alert` or
`Remediating`, the first heartbeat tick self-prompts: *"You were mid-incident at
shutdown — review state_snapshots and the open episode before accepting new work."*
That boot-time recall, plus episodic retrieval in the prompt, is what makes identity
feel continuous across restarts.

---

## 4. Cross-Language Transport Contract (Rust ⇄ Python)

All Rust→Python signaling uses append-only JSONL under the workspace (atomic
line-append, tail-friendly, replayable; the pattern `episodic_memory_ingestor.py`
already uses). Every line carries `schema_version`. Unknown keys ignored on read.

| File | Writer | Reader | Line schema |
|---|---|---|---|
| `episodic_memory/episodic_events.jsonl` | Rust tool-execution hook | `episodic_memory_ingestor.py` | `EpisodicEventV2` (§3.2) |
| `episodic_memory/episodes.jsonl` | Python ingestor | Rust (boot recall), `memory_remediation.py` | `Episode` (§3.2) |
| `runtime/state_snapshots.jsonl` | Rust state machine | `autonomy_supervisor.py` | `BehavioralStateSnapshot` + `transition` |
| `runtime/vitals.jsonl` | Rust `VitalsMonitor` | `stagnation_monitor.py` (lab), supervisor | `{verdict, intervention, turn_id, ts}` |
| `runtime/sensory_dropped.jsonl` | Rust bus (overflow digests) | supervisor | `{lane, coalesce_key, dropped, window_ts}` |

Python→Rust direction goes through existing authenticated surfaces only (gateway API
/ memory CLI) — Python never writes Rust-owned state files, which keeps a single
writer per file and makes corruption and races structurally impossible.

## 5. Python Orchestration: `autonomy_supervisor.py`

One asyncio supervisor owns the offline tier (mirrors the Rust driver's shape):

```python
import asyncio, contextlib

class AutonomySupervisor:
    """Offline tier: tails Rust JSONL streams, runs ingestion/consolidation,
    escalates out-of-band. One task per concern, supervised with backoff
    (same philosophy as src/channels/listener.rs)."""

    def __init__(self, ingestor, stagnation, remediation, alerter, paths):
        self._tasks: list[asyncio.Task] = []
        self._stop = asyncio.Event()
        self.ingestor, self.stagnation = ingestor, stagnation
        self.remediation, self.alerter, self.paths = remediation, alerter, paths

    async def run(self) -> None:
        spawn = lambda coro, name: self._tasks.append(
            asyncio.create_task(self._supervise(coro, name), name=name))
        spawn(self.ingestor.run, "episodic_ingest")          # events → episodes → vectors
        spawn(self._tail_vitals, "vitals_tail")              # mirror in-loop verdicts
        spawn(self._tail_state, "state_tail")                # alert on Alert/Remediating
        spawn(self._remediation_pass, "remediation")         # hourly evidence gathering
        await self._stop.wait()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _supervise(self, factory, name: str) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                await factory()
                backoff = 1.0                                # clean exit resets
            except asyncio.CancelledError:
                raise
            except Exception as exc:                         # noqa: BLE001 — supervisor boundary
                await self.alerter.debug(f"{name} crashed: {exc!r}; retry in {backoff:.0f}s")
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                backoff = min(backoff * 2, 300.0)

    async def _tail_state(self) -> None:
        async for snap in tail_jsonl(self.paths.state_snapshots):   # shared tailer util
            if snap.get("state") in ("alert", "remediating"):
                await self.alerter.notify(
                    f"R.A.I.N._runtime entered {snap['state']}: {snap.get('cause', '?')}")
```

`tail_jsonl` is extracted from `episodic_memory_ingestor.py`'s existing tailing logic
into a shared utility (rule-of-three is satisfied: ingestor, vitals tail, state tail).
The alerter delivers via the same channel configured for the heartbeat dead-man's
switch — one out-of-band path, not two.

## 6. Config Schema Additions

Follows the existing serde pattern (`#[serde(default)]`, defaults as functions,
backward compatible — absent sections mean "feature off"):

```toml
# NOTE: named `autonomous_runtime` because `[autonomy]` is already the
# security-policy section (AutonomyConfig / AutonomyLevel).
[autonomous_runtime]
enabled = false                     # master switch; false = exactly today's behavior
max_concurrent_pulses = 2
state_persistence = true
max_remediation_attempts = 3
cooldown_secs = 120

[autonomous_runtime.vitals]
dead_end_window = 3
dead_end_similarity = 0.95
stagnation_window = 5
stagnation_novelty_mean = 0.15
max_rss_mb = 0                      # 0 = unlimited
max_turn_tokens = 0

[senses]
enabled = false
lane_capacity = [8, 64, 256, 256]   # P0..P3
starvation_credit = 16
ambient_facts = 32
ambient_token_budget = 1000
coalesce_window_ms = 2000

[episodic]
enabled = false
gap_minutes = 20
drift_threshold = 0.55              # only used when embeddings configured
salience_floor = 0.05
decay_factor = 0.97                 # per week
```

`[heartbeat]` keeps its exact current meaning; when `[autonomous_runtime].enabled = true` the
engine runs as the `heartbeat_md` pulse with identical user-visible behavior
(HEARTBEAT.md format, two-phase decision, adaptive interval, dead-man's switch).
Documented migration: none required.

## 7. Integration Diff Map (where code actually changes)

| File | Change |
|---|---|
| `src/autonomy/{mod,traits,driver,context,vitals,state,episodic}.rs` | **New** — driver, pulse registry/factory, vitals, state machine, episode types |
| `src/senses/{mod,traits,event,bus,ambient,factory}.rs` | **New** — envelope, Sense trait, lanes, ambient buffer, adapters |
| `src/heartbeat/engine.rs` | Engine logic kept; `run()` loop body extracted into `HeartbeatMdPulse: PulseTask` (legacy standalone loop retained behind `autonomous_runtime.enabled = false`) |
| `src/channels/dispatch.rs` | Head of loop reads from `SensoryBus::next()` when senses enabled; `/stop` path unchanged |
| `src/agent/loop_.rs` | `VitalsMonitor::observe_iteration` call beside existing loop-detection block; `StatePolicy` pacing/iteration factors applied at loop entry |
| `src/agent/tool_filter.rs` | Intersect `ToolGate` with existing filters |
| `src/agent/prompt.rs` | Ambient section + tone directive + top-k episodic recall in `SystemPromptBuilder` |
| `src/observability/traits.rs` | New events (§8) |
| `src/config/schema/mod.rs` | `[autonomous_runtime]`, `[senses]`, `[episodic]` sections |
| `python/rain_contracts/episodic.py`, `autonomy_supervisor.py` | **New** — contracts + supervisor |
| `episodic_memory_ingestor.py` | Adopt `EpisodicEventV2.from_jsonl` (accepts v1 lines unchanged); add segmentation per §3.3 |

## 8. Observability Additions

New `ObserverEvent` variants (additive, non-breaking):

```rust
PulseTick        { task: String, outcome: String, duration: Duration },
VitalsIntervention { verdict: String, intervention: String },
StateTransition  { from: String, to: String, cause: String },
SensoryDropped   { lane: String, count: u64 },
EpisodeClosed    { episode_id: String, event_count: u32, salience: f64 },
```

Prometheus mappings: `rain_pulse_ticks_total{task,outcome}`,
`rain_state{state}` gauge, `rain_sensory_dropped_total{lane}`,
`rain_vitals_interventions_total{intervention}`. None of these carry payload content
— labels only (no sensitive data in metrics).

## 9. Failure Modes & Mitigations

| Failure | Mitigation |
|---|---|
| Pulse task hangs | Per-tick `timeout(budget.max_duration)`; consecutive failures back off via `compute_adaptive_interval` |
| Event storm (chatty sensor, webhook flood) | Coalescing + `DropOldest` on P2/P3 with counted, logged digests; P1 `RejectNewest` returns visible error to channel |
| Self-prompt loop (agent ticks itself into a spiral) | `SelfPrompt` events carry the originating task name; per-task `min_gap` debounce + vitals dead-end detection on resulting turns |
| State thrash (Alert↔Remediating oscillation) | `cooldown_secs` healthy-period requirement + `max_remediation_attempts` hard stop → operator wait |
| Ambient leakage into permanent memory | Buffer never touches `Memory`; `ambient_echo` tagging + hygiene prune; promotion only via episode close with provenance |
| JSONL reader/writer races | Single-writer-per-file rule (§4); appends are line-atomic; readers tolerate partial trailing lines |
| Restart mid-incident | State + open-episode restore on boot; first tick self-prompts incident review before new work |
| Runaway provider spend from autonomy | Pulse budgets (`max_llm_calls`) + existing cost tracker; `vitals` pulse enforces `max_turn_tokens` |

## 10. Rollout Plan (phased, each independently revertable)

1. **PR-1 (Medium risk):** `src/autonomy/` driver + traits + vitals; `HeartbeatEngine`
   wrapped as `heartbeat_md` pulse behind `autonomous_runtime.enabled = false` default.
   Rollback: flip flag / revert — legacy loop untouched.
2. **PR-2 (Medium):** `src/senses/` bus + ambient buffer; channels adapter behind
   `senses.enabled`. Dispatch loop falls back to direct mpsc when disabled.
3. **PR-3 (Low):** episodic contracts (Rust + Python), v2 event writer, ingestor
   segmentation. Pure additive JSONL fields.
4. **PR-4 (High):** state machine + tool gating + loop_.rs vitals integration.
   Requires boundary tests: gate-only-narrows property test, transition-table
   exhaustiveness, intervention-ladder tests.
5. **PR-5 (Low):** `autonomy_supervisor.py`, docs runtime-contract updates
   (`config-reference`, `operations-runbook` + fr/vi locales per CLAUDE.md §4.1).

Validation per phase: `cargo fmt --check`, `cargo clippy -D warnings`, `cargo test`,
plus phase-specific: lane-overflow/starvation tests (PR-2), v1↔v2 JSONL round-trip
tests in both languages (PR-3), tool-gate intersection property tests (PR-4).

## 11. Non-Goals

- No new heavy dependencies (no actor frameworks, no embedded brokers; tokio
  primitives + serde only — `tokio-util` is already in the tree).
- No autonomous capability *expansion*: states and pulses can only narrow what the
  existing `SecurityPolicy`/`AutonomyLevel` already permit.
- No replacement of the cron scheduler — minute-plus scheduled jobs stay in
  `src/cron/`; the pulse driver covers sub-minute reflexes and event-driven wakes.
- No real-identity affect modeling: affect traces are system-behavioral signals
  (valence/arousal over outcomes), not user profiling.
