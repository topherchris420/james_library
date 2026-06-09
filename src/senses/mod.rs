//! Unified sensory intake: a prioritized, bounded event bus between the
//! environment (channels, peripherals, watchers) and the reasoning loop.
//!
//! Enabled via `[senses]` (default off). When enabled, channel listener
//! traffic is interposed through the bus so stop commands (P0) overtake
//! queued messages (P1) and telemetry (P2/P3) can never flood the dispatch
//! path. Design: `docs/autonomous-runtime-design.md` §2.

pub mod ambient;
pub mod bus;
pub mod event;

pub use ambient::{AmbientContextBuffer, AmbientFact};
pub use event::{SensePayload, SensePriority, SensoryEvent};

use std::sync::Arc;

/// Shared handle to the ambient buffer (filled by the bus router, read by
/// the prompt builder in a later phase).
pub type SharedAmbientBuffer = Arc<parking_lot::Mutex<AmbientContextBuffer>>;

/// Interpose the sensory bus between channel listeners and the dispatch
/// loop.
///
/// Listener messages are classified by `classify` (stop commands → P0
/// `Interrupt`, everything else → P1 `Direct`), published into the bus, and
/// drained back out in priority order to a fresh mpsc receiver with the same
/// item type the dispatch loop already consumes. `Observation` events fold
/// into the returned ambient buffer instead of reaching dispatch.
///
/// Shutdown propagates exactly like the direct mpsc path: when all listeners
/// stop, `raw_rx` closes → the bus closes → the returned receiver closes →
/// the dispatch loop exits.
pub fn interpose_channel_bus(
    mut raw_rx: tokio::sync::mpsc::Receiver<crate::channels::traits::ChannelMessage>,
    config: &crate::config::SensesConfig,
    classify: impl Fn(&crate::channels::traits::ChannelMessage) -> SensePriority + Send + Sync + 'static,
) -> (
    tokio::sync::mpsc::Receiver<crate::channels::traits::ChannelMessage>,
    SharedAmbientBuffer,
) {
    let (bus, mut bus_rx) = bus::channel(config);
    let ambient: SharedAmbientBuffer = Arc::new(parking_lot::Mutex::new(
        AmbientContextBuffer::new(config.ambient_facts),
    ));

    // Intake: raw listener messages → classified bus events. Block-policy
    // lanes preserve the bounded-mpsc backpressure this path used to have.
    tokio::spawn(async move {
        while let Some(msg) = raw_rx.recv().await {
            let priority = classify(&msg);
            let event = SensoryEvent::new(
                format!("channel:{}", msg.channel),
                priority,
                SensePayload::ChannelMessage(msg),
            );
            if let Err(e) = bus.publish(event).await {
                tracing::warn!("sensory intake stopped: {e}");
                break;
            }
        }
        bus.close();
    });

    // Drain: bus events in priority order → dispatch mpsc / ambient buffer.
    let (out_tx, out_rx) = tokio::sync::mpsc::channel(1);
    let drain_ambient = Arc::clone(&ambient);
    tokio::spawn(async move {
        while let Some(event) = bus_rx.next().await {
            match event.payload {
                SensePayload::ChannelMessage(msg) => {
                    if out_tx.send(msg).await.is_err() {
                        // Dispatch loop gone; stop draining.
                        break;
                    }
                }
                SensePayload::Observation { text } => {
                    let now = chrono::Utc::now();
                    let fact = AmbientFact {
                        source: event.source.clone(),
                        text,
                        observed_at: event.observed_at,
                        expires_at: event
                            .expires_at
                            .unwrap_or(now + chrono::Duration::minutes(5)),
                        fold_count: event.folds,
                    };
                    let key = event.coalesce_key.unwrap_or(event.source);
                    drain_ambient.lock().upsert(key, fact);
                }
            }
        }
    });

    (out_rx, ambient)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::channels::traits::ChannelMessage;

    fn msg(content: &str) -> ChannelMessage {
        ChannelMessage {
            id: "test-id".into(),
            sender: "test_user".into(),
            reply_target: "test_user".into(),
            content: content.into(),
            channel: "telegram".into(),
            timestamp: 0,
            thread_ts: None,
            interruption_scope_id: None,
            attachments: vec![],
        }
    }

    #[tokio::test]
    async fn interposed_messages_flow_through_in_order() {
        let (raw_tx, raw_rx) = tokio::sync::mpsc::channel(8);
        let (mut out_rx, _ambient) =
            interpose_channel_bus(raw_rx, &crate::config::SensesConfig::default(), |_| {
                SensePriority::Direct
            });

        raw_tx.send(msg("first")).await.unwrap();
        raw_tx.send(msg("second")).await.unwrap();
        drop(raw_tx);

        assert_eq!(out_rx.recv().await.unwrap().content, "first");
        assert_eq!(out_rx.recv().await.unwrap().content, "second");
        // Listener shutdown propagates: receiver closes.
        assert!(out_rx.recv().await.is_none());
    }

    #[tokio::test]
    async fn interrupt_classification_overtakes_queued_messages() {
        let (raw_tx, raw_rx) = tokio::sync::mpsc::channel(8);
        let (mut out_rx, _ambient) =
            interpose_channel_bus(raw_rx, &crate::config::SensesConfig::default(), |m| {
                if m.content == "/stop" {
                    SensePriority::Interrupt
                } else {
                    SensePriority::Direct
                }
            });

        // The drain task hands "a" to the (capacity-1) output, then parks in
        // `out_tx.send("b")` because nothing is consuming yet. "c" and the
        // stop command therefore queue inside the bus, where the interrupt
        // lane overtakes the direct lane. The sleeps let the single-threaded
        // test runtime run the intake/drain tasks between sends.
        let settle = || tokio::time::sleep(std::time::Duration::from_millis(50));
        raw_tx.send(msg("a")).await.unwrap();
        settle().await;
        raw_tx.send(msg("b")).await.unwrap();
        settle().await;
        raw_tx.send(msg("c")).await.unwrap();
        raw_tx.send(msg("/stop")).await.unwrap();
        settle().await;
        drop(raw_tx);

        let mut order = Vec::new();
        while let Some(m) = out_rx.recv().await {
            order.push(m.content);
        }
        let stop_pos = order.iter().position(|c| c == "/stop").unwrap();
        let c_pos = order.iter().position(|c| c == "c").unwrap();
        assert!(
            stop_pos < c_pos,
            "stop command should overtake queued messages: {order:?}"
        );
    }
}
