use super::{
    Arc, AtomicU64, CancellationToken, ChannelRuntimeContext, HashMap, InFlightSenderTaskState,
    InFlightTaskCompletion, Ordering, SendMessage, interruption_scope_key, is_stop_command,
    log_worker_join_result, process_channel_message, traits,
};

pub(super) async fn run_message_dispatch_loop(
    mut rx: tokio::sync::mpsc::Receiver<traits::ChannelMessage>,
    ctx: Arc<ChannelRuntimeContext>,
    max_in_flight_messages: usize,
) {
    let semaphore = Arc::new(tokio::sync::Semaphore::new(max_in_flight_messages));
    let mut workers = tokio::task::JoinSet::new();
    let in_flight_by_sender = Arc::new(tokio::sync::Mutex::new(HashMap::<
        String,
        InFlightSenderTaskState,
    >::new()));
    let task_sequence = Arc::new(AtomicU64::new(1));

    while let Some(msg) = rx.recv().await {
        if msg.channel != "cli" && is_stop_command(&msg.content) {
            let scope_key = interruption_scope_key(&msg);
            let previous = {
                let mut active = in_flight_by_sender.lock().await;
                active.remove(&scope_key)
            };
            let reply = if let Some(state) = previous {
                state.cancellation.cancel();
                "Stop signal sent.".to_string()
            } else {
                "No in-flight task for this sender scope.".to_string()
            };
            let channel = ctx
                .channels_by_name
                .get(&msg.channel)
                .or_else(|| {
                    msg.channel
                        .split_once(':')
                        .and_then(|(base, _)| ctx.channels_by_name.get(base))
                })
                .cloned();
            if let Some(channel) = channel {
                let reply_target = msg.reply_target.clone();
                let thread_ts = msg.thread_ts.clone();
                tokio::spawn(async move {
                    let _ = channel
                        .send(&SendMessage::new(reply, &reply_target).in_thread(thread_ts))
                        .await;
                });
            } else {
                tracing::warn!(
                    channel = %msg.channel,
                    "stop command: no registered channel found for reply"
                );
            }
            continue;
        }

        let permit = match Arc::clone(&semaphore).acquire_owned().await {
            Ok(permit) => permit,
            Err(_) => break,
        };

        let worker_ctx = Arc::clone(&ctx);
        let in_flight = Arc::clone(&in_flight_by_sender);
        let task_sequence = Arc::clone(&task_sequence);
        workers.spawn(async move {
            let _permit = permit;
            let interrupt_enabled = worker_ctx
                .interrupt_on_new_message
                .enabled_for_channel(msg.channel.as_str());
            let sender_scope_key = interruption_scope_key(&msg);
            let cancellation_token = CancellationToken::new();
            let completion = Arc::new(InFlightTaskCompletion::new());
            let task_id = task_sequence.fetch_add(1, Ordering::Relaxed) as u64;

            let register_in_flight = msg.channel != "cli";
            if register_in_flight {
                let previous = {
                    let mut active = in_flight.lock().await;
                    active.insert(
                        sender_scope_key.clone(),
                        InFlightSenderTaskState {
                            task_id,
                            cancellation: cancellation_token.clone(),
                            completion: Arc::clone(&completion),
                        },
                    )
                };

                if interrupt_enabled {
                    if let Some(previous) = previous {
                        tracing::info!(
                            channel = %msg.channel,
                            sender = %msg.sender,
                            "Interrupting previous in-flight request for sender"
                        );
                        previous.cancellation.cancel();
                        previous.completion.wait().await;
                    }
                }
            }

            process_channel_message(worker_ctx, msg, cancellation_token).await;

            if register_in_flight {
                let mut active = in_flight.lock().await;
                if active
                    .get(&sender_scope_key)
                    .is_some_and(|state| state.task_id == task_id)
                {
                    active.remove(&sender_scope_key);
                }
            }

            completion.mark_done();
        });

        while let Some(result) = workers.try_join_next() {
            log_worker_join_result(result);
        }
    }

    while let Some(result) = workers.join_next().await {
        log_worker_join_result(result);
    }
}
