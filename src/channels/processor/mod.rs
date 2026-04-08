//! Message processing pipeline and context building.

use anyhow::Result;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio_util::sync::CancellationToken;

use crate::observability::{Observer, runtime_trace};
use crate::security::AutonomyLevel;
use crate::memory;
use crate::memory::Memory;
use crate::providers;
use crate::observability::traits::ObserverEvent;
use crate::channels::traits;

use crate::channels::{
    AUTOSAVE_MIN_MESSAGE_CHARS, CHANNEL_MESSAGE_TIMEOUT_SCALE_CAP,
    ChannelNotifyObserver, channel_message_timeout_budget_secs_with_cap,
    log_worker_join_result, normalize_cached_channel_turns, spawn_scoped_typing_task,
    strip_tool_result_content, ChannelRuntimeContext, CHANNEL_HOOK_MAX_OUTBOUND_CHARS, PROACTIVE_CONTEXT_BUDGET_CHARS,
    MEMORY_CONTEXT_MAX_CHARS, MEMORY_CONTEXT_MAX_ENTRIES,
    MEMORY_CONTEXT_ENTRY_MAX_CHARS,
    traits::{Channel, SendMessage},
    history::{
        append_sender_turn, compact_sender_history, proactive_trim_turns, rollback_orphan_user_turn,
    },
    runtime_state::{
        clear_sender_history, conversation_history_key, conversation_memory_key,
        followup_thread_id, get_route_selection,
        mark_sender_for_new_session, maybe_apply_runtime_config_update, parse_runtime_command,
        resolve_provider_alias, set_route_selection, take_pending_new_session,
        runtime_defaults_snapshot,
    },
    sanitize::sanitize_channel_response,
    provider,
    ChatMessage, ChannelRouteSelection, ChannelRuntimeCommand, Provider,
    is_model_switch_requested, render_runtime_system_prompt, scrub_credentials,
    RuntimeSystemPromptContext, truncate_with_ellipsis,
};
use crate::channels::prompt::{build_channel_system_prompt};
use std::fmt::Write as _;

pub(crate) fn should_skip_memory_context_entry(key: &str, content: &str) -> bool {
    if memory::is_assistant_autosave_key(key) {
        return true;
    }

    if memory::should_skip_autosave_content(content) {
        return true;
    }

    if key.trim().to_ascii_lowercase().ends_with("_history") {
        return true;
    }

    // Skip entries containing image markers to prevent duplication.
    // When auto_save stores a photo message to memory, a subsequent
    // memory recall on the same turn would surface the marker again,
    // causing two identical image blocks in the provider request.
    if content.contains("[IMAGE:") {
        return true;
    }

    // Skip entries containing tool_result blocks. After a daemon restart
    // these can be recalled from SQLite and injected as memory context,
    // presenting the LLM with a `<tool_result>` without a preceding
    // `<tool_call>` and triggering hallucinated output.
    if content.contains("<tool_result") {
        return true;
    }

    content.chars().count() > MEMORY_CONTEXT_MAX_CHARS
}

pub(crate) fn is_context_window_overflow_error(err: &anyhow::Error) -> bool {
    let lower = err.to_string().to_lowercase();
    [
        "exceeds the context window",
        "context window of this model",
        "maximum context length",
        "context length exceeded",
        "too many tokens",
        "token limit exceeded",
        "prompt is too long",
        "input is too long",
    ]
    .iter()
    .any(|hint| lower.contains(hint))
}

async fn handle_runtime_command_if_needed(
    ctx: &ChannelRuntimeContext,
    msg: &traits::ChannelMessage,
    target_channel: Option<&Arc<dyn Channel>>,
) -> bool {
    let Some(command) = parse_runtime_command(&msg.channel, &msg.content) else {
        return false;
    };

    let Some(channel) = target_channel else {
        return true;
    };

    let sender_key = conversation_history_key(msg);
    let mut current = get_route_selection(ctx, &sender_key);

    let response = match command {
        ChannelRuntimeCommand::ShowProviders => provider::build_providers_help_response(&current),
        ChannelRuntimeCommand::SetProvider(raw_provider) => {
            match resolve_provider_alias(&raw_provider) {
                Some(provider_name) => {
                    match ctx.provider_manager().get_or_create_with_key(&provider_name, None).await {
                        Ok(_) => {
                            if provider_name != current.provider {
                                current.provider = provider_name.clone();
                                set_route_selection(ctx, &sender_key, current.clone());
                            }

                            format!(
                                "Provider switched to `{provider_name}` for this sender session. Current model is `{}`.\nUse `/model <model-id>` to set a provider-compatible model.",
                                current.model
                            )
                        }
                        Err(err) => {
                            let safe_err = providers::sanitize_api_error(&err.to_string());
                            format!(
                                "Failed to initialize provider `{provider_name}`. Route unchanged.\nDetails: {safe_err}"
                            )
                        }
                    }
                }
                None => format!(
                    "Unknown provider `{raw_provider}`. Use `/models` to list valid providers."
                ),
            }
        }
        ChannelRuntimeCommand::ShowModel => {
            provider::build_models_help_response(&current, ctx.workspace_dir.as_path(), &ctx.model_routes)
        }
        ChannelRuntimeCommand::SetModel(raw_model) => {
            let model = raw_model.trim().trim_matches('`').to_string();
            if model.is_empty() {
                "Model ID cannot be empty. Use `/model <model-id>`.".to_string()
            } else {
                // Resolve provider+model from model_routes (match by model name or hint)
                if let Some(route) = ctx.model_routes.iter().find(|r| {
                    r.model.eq_ignore_ascii_case(&model) || r.hint.eq_ignore_ascii_case(&model)
                }) {
                    current.provider = route.provider.clone();
                    current.model = route.model.clone();
                    current.api_key = route.api_key.clone();
                } else {
                    current.model = model.clone();
                }
                set_route_selection(ctx, &sender_key, current.clone());

                format!(
                    "Model switched to `{}` (provider: `{}`). Context preserved.",
                    current.model, current.provider
                )
            }
        }
        ChannelRuntimeCommand::NewSession => {
            clear_sender_history(ctx, &sender_key);
            if let Some(ref store) = ctx.session_store {
                if let Err(e) = store.delete_session(&sender_key) {
                    tracing::warn!("Failed to delete persisted session for {sender_key}: {e}");
                }
            }
            mark_sender_for_new_session(ctx, &sender_key);
            "Conversation history cleared. Starting fresh.".to_string()
        }
    };

    if let Err(err) = channel
        .send(&SendMessage::new(response, &msg.reply_target).in_thread(msg.thread_ts.clone()))
        .await
    {
        tracing::warn!(
            "Failed to send runtime command response on {}: {err}",
            channel.name()
        );
    }

    true
}

pub(crate) async fn build_memory_context(
    mem: &dyn Memory,
    user_msg: &str,
    min_relevance_score: f64,
    session_id: Option<&str>,
) -> String {
    let mut context = String::new();

    if let Ok(entries) = mem.recall(user_msg, 5, session_id, None, None).await {
        let mut included = 0usize;
        let mut used_chars = 0usize;

        for entry in entries.iter().filter(|e| match e.score {
            Some(score) => score >= min_relevance_score,
            None => true, // keep entries without a score (e.g. non-vector backends)
        }) {
            if included >= MEMORY_CONTEXT_MAX_ENTRIES {
                break;
            }

            if should_skip_memory_context_entry(&entry.key, &entry.content) {
                continue;
            }

            let content = if entry.content.chars().count() > MEMORY_CONTEXT_ENTRY_MAX_CHARS {
                truncate_with_ellipsis(&entry.content, MEMORY_CONTEXT_ENTRY_MAX_CHARS)
            } else {
                entry.content.clone()
            };

            let line = format!("- {}: {}\n", entry.key, content);
            let line_chars = line.chars().count();
            if used_chars + line_chars > MEMORY_CONTEXT_MAX_CHARS {
                break;
            }

            if included == 0 {
                context.push_str("[Memory context]\n");
            }

            context.push_str(&line);
            used_chars += line_chars;
            included += 1;
        }

        if included > 0 {
            context.push('\n');
        }
    }

    context
}

/// Extract a compact summary of tool interactions from history messages added
/// during `run_tool_call_loop`. Scans assistant messages for `<tool_call>` tags
/// or native tool-call JSON to collect tool names used.
/// Returns an empty string when no tools were invoked.
pub(crate) fn extract_tool_context_summary(history: &[ChatMessage], start_index: usize) -> String {
    fn push_unique_tool_name(tool_names: &mut Vec<String>, name: &str) {
        let candidate = name.trim();
        if candidate.is_empty() {
            return;
        }
        if !tool_names.iter().any(|existing| existing == candidate) {
            tool_names.push(candidate.to_string());
        }
    }

    fn collect_tool_names_from_tool_call_tags(content: &str, tool_names: &mut Vec<String>) {
        const TAG_PAIRS: [(&str, &str); 4] = [
            ("<tool_call>", "</tool_call>"),
            ("<toolcall>", "</toolcall>"),
            ("<tool-call>", "</tool-call>"),
            ("<invoke>", "</invoke>"),
        ];

        for (open_tag, close_tag) in TAG_PAIRS {
            for segment in content.split(open_tag) {
                if let Some(json_end) = segment.find(close_tag) {
                    let json_str = segment[..json_end].trim();
                    if let Ok(val) = serde_json::from_str::<serde_json::Value>(json_str) {
                        if let Some(name) = val.get("name").and_then(|n| n.as_str()) {
                            push_unique_tool_name(tool_names, name);
                        }
                    }
                }
            }
        }
    }

    fn collect_tool_names_from_native_json(content: &str, tool_names: &mut Vec<String>) {
        if let Ok(val) = serde_json::from_str::<serde_json::Value>(content) {
            if let Some(calls) = val.get("tool_calls").and_then(|c| c.as_array()) {
                for call in calls {
                    let name = call
                        .get("function")
                        .and_then(|f| f.get("name"))
                        .and_then(|n| n.as_str())
                        .or_else(|| call.get("name").and_then(|n| n.as_str()));
                    if let Some(name) = name {
                        push_unique_tool_name(tool_names, name);
                    }
                }
            }
        }
    }

    fn collect_tool_names_from_tool_results(content: &str, tool_names: &mut Vec<String>) {
        let marker = "<tool_result name=\"";
        let mut remaining = content;
        while let Some(start) = remaining.find(marker) {
            let name_start = start + marker.len();
            let after_name_start = &remaining[name_start..];
            if let Some(name_end) = after_name_start.find('"') {
                let name = &after_name_start[..name_end];
                push_unique_tool_name(tool_names, name);
                remaining = &after_name_start[name_end + 1..];
            } else {
                break;
            }
        }
    }

    let mut tool_names: Vec<String> = Vec::new();

    for msg in history.iter().skip(start_index) {
        match msg.role.as_str() {
            "assistant" => {
                collect_tool_names_from_tool_call_tags(&msg.content, &mut tool_names);
                collect_tool_names_from_native_json(&msg.content, &mut tool_names);
            }
            "user" => {
                // Prompt-mode tool calls are always followed by [Tool results] entries
                // containing `<tool_result name="...">` tags with canonical tool names.
                collect_tool_names_from_tool_results(&msg.content, &mut tool_names);
            }
            _ => {}
        }
    }

    if tool_names.is_empty() {
        return String::new();
    }

    format!("[Used tools: {}]", tool_names.join(", "))
}


pub(crate) async fn process_channel_message(
    ctx: Arc<ChannelRuntimeContext>,
    msg: traits::ChannelMessage,
    cancellation_token: CancellationToken,
) {
    if cancellation_token.is_cancelled() {
        return;
    }

    println!(
        "  💬 [{}] from {}: {}",
        msg.channel,
        msg.sender,
        truncate_with_ellipsis(&msg.content, 80)
    );
    runtime_trace::record_event(
        "channel_message_inbound",
        Some(msg.channel.as_str()),
        None,
        None,
        None,
        None,
        None,
        serde_json::json!({
            "sender": msg.sender,
            "message_id": msg.id,
            "reply_target": msg.reply_target,
            "content_preview": truncate_with_ellipsis(&msg.content, 160),
        }),
    );

    // ── Hook: on_message_received (modifying) ────────────
    let mut msg = if let Some(hooks) = &ctx.hooks {
        match hooks.run_on_message_received(msg).await {
            crate::hooks::HookResult::Cancel(reason) => {
                tracing::info!(%reason, "incoming message dropped by hook");
                return;
            }
            crate::hooks::HookResult::Continue(modified) => modified,
        }
    } else {
        msg
    };

    let target_channel = ctx
        .channels_by_name
        .get(&msg.channel)
        .or_else(|| {
            // Multi-room channels use "name:qualifier" format (e.g. "matrix:!roomId");
            // fall back to base channel name for routing.
            msg.channel
                .split_once(':')
                .and_then(|(base, _)| ctx.channels_by_name.get(base))
        })
        .cloned();
    if let Err(err) = maybe_apply_runtime_config_update(ctx.as_ref()).await {
        tracing::warn!("Failed to apply runtime config update: {err}");
    }
    if handle_runtime_command_if_needed(ctx.as_ref(), &msg, target_channel.as_ref()).await {
        return;
    }

    let history_key = conversation_history_key(&msg);
    let mut route = get_route_selection(ctx.as_ref(), &history_key);

    // ── Query classification: override route when a rule matches ──
    if let Some(hint) = crate::agent::classifier::classify(&ctx.query_classification, &msg.content)
    {
        if let Some(matched_route) = ctx
            .model_routes
            .iter()
            .find(|r| r.hint.eq_ignore_ascii_case(&hint))
        {
            tracing::info!(
                target: "query_classification",
                hint = hint.as_str(),
                provider = matched_route.provider.as_str(),
                model = matched_route.model.as_str(),
                channel = %msg.channel,
                "Channel message classified — overriding route"
            );
            route = ChannelRouteSelection {
                provider: matched_route.provider.clone(),
                model: matched_route.model.clone(),
                api_key: matched_route.api_key.clone(),
            };
        }
    }

    let runtime_defaults = runtime_defaults_snapshot(ctx.as_ref());
    let mut active_provider = match ctx.as_ref().provider_manager().get_or_create_with_key(
        &route.provider,
        route.api_key.as_deref(),
    )
    .await
    {
        Ok(provider) => provider,
        Err(err) => {
            let safe_err = providers::sanitize_api_error(&err.to_string());
            let message = format!(
                "⚠️ Failed to initialize provider `{}`. Please run `/models` to choose another provider.\nDetails: {safe_err}",
                route.provider
            );
            if let Some(channel) = target_channel.as_ref() {
                let _ = channel
                    .send(
                        &SendMessage::new(message, &msg.reply_target)
                            .in_thread(msg.thread_ts.clone()),
                    )
                    .await;
            }
            return;
        }
    };
    if ctx.auto_save_memory
        && msg.content.chars().count() >= AUTOSAVE_MIN_MESSAGE_CHARS
        && !memory::should_skip_autosave_content(&msg.content)
    {
        let autosave_key = conversation_memory_key(&msg);
        let _ = ctx
            .memory
            .store(
                &autosave_key,
                &msg.content,
                crate::memory::MemoryCategory::Conversation,
                Some(&history_key),
            )
            .await;
    }

    println!("  ⏳ Processing message...");
    let started_at = Instant::now();

    let force_fresh_session = take_pending_new_session(ctx.as_ref(), &history_key);
    if force_fresh_session {
        // `/new` should make the next user turn completely fresh even if
        // older cached turns reappear before this message starts.
        clear_sender_history(ctx.as_ref(), &history_key);
    }

    let _had_prior_history = if force_fresh_session {
        false
    } else {
        ctx.conversation_histories
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .get(&history_key)
            .is_some_and(|turns| !turns.is_empty())
    };

    // Preserve user turn before the LLM call so interrupted requests keep context.
    append_sender_turn(ctx.as_ref(), &history_key, ChatMessage::user(&msg.content));

    // Build history from per-sender conversation cache.
    let prior_turns_raw = if force_fresh_session {
        vec![ChatMessage::user(&msg.content)]
    } else {
        ctx.conversation_histories
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .get(&history_key)
            .cloned()
            .unwrap_or_default()
    };
    let mut prior_turns = normalize_cached_channel_turns(prior_turns_raw);

    // Strip stale tool_result blocks from cached turns so the LLM never
    // sees a `<tool_result>` without a preceding `<tool_call>`, which
    // causes hallucinated output on subsequent heartbeat ticks or sessions.
    for turn in &mut prior_turns {
        if turn.content.contains("<tool_result") {
            turn.content = strip_tool_result_content(&turn.content);
        }
    }

    // Strip [IMAGE:] markers from *older* history messages when the active
    // provider does not support vision. This prevents "history poisoning"
    // where a previously-sent image marker gets reloaded from the JSONL
    // session file and permanently breaks the conversation (fixes #3674).
    // We skip the last turn (the current message) so the vision check can
    // still reject fresh image sends with a proper error.
    if !active_provider.supports_vision() && prior_turns.len() > 1 {
        let last_idx = prior_turns.len() - 1;
        for turn in &mut prior_turns[..last_idx] {
            if turn.content.contains("[IMAGE:") {
                let (cleaned, _refs) = crate::multimodal::parse_image_markers(&turn.content);
                turn.content = cleaned;
            }
        }
        // Drop older turns that became empty after marker removal (e.g. image-only messages).
        // Keep the last turn (current message) intact.
        let current = prior_turns.pop();
        prior_turns.retain(|turn| !turn.content.trim().is_empty());
        if let Some(current) = current {
            prior_turns.push(current);
        }
    }

    // Proactively trim conversation history before sending to the provider
    // to prevent context-window-exceeded errors (bug #3460).
    let dropped = proactive_trim_turns(&mut prior_turns, PROACTIVE_CONTEXT_BUDGET_CHARS);
    if dropped > 0 {
        tracing::info!(
            channel = %msg.channel,
            sender = %msg.sender,
            dropped_turns = dropped,
            remaining_turns = prior_turns.len(),
            "Proactively trimmed conversation history to fit context budget"
        );
    }

    // ── Dual-scope memory recall ──────────────────────────────────
    // Always recall before each LLM call (not just first turn).
    // For group chats: merge sender-scope + group-scope memories.
    // For DMs: sender-scope only.
    let is_group_chat =
        msg.reply_target.contains("@g.us") || msg.reply_target.starts_with("group:");

    let mem_recall_start = Instant::now();
    let sender_memory_fut = build_memory_context(
        ctx.memory.as_ref(),
        &msg.content,
        ctx.min_relevance_score,
        Some(&msg.sender),
    );

    let (sender_memory, group_memory) = if is_group_chat {
        let group_memory_fut = build_memory_context(
            ctx.memory.as_ref(),
            &msg.content,
            ctx.min_relevance_score,
            Some(&history_key),
        );
        tokio::join!(sender_memory_fut, group_memory_fut)
    } else {
        (sender_memory_fut.await, String::new())
    };
    #[allow(clippy::cast_possible_truncation)]
    let mem_recall_ms = mem_recall_start.elapsed().as_millis() as u64;
    tracing::info!(
        mem_recall_ms,
        sender_empty = sender_memory.is_empty(),
        group_empty = group_memory.is_empty(),
        "⏱ Memory recall completed"
    );

    // Merge sender + group memories, avoiding duplicates
    let memory_context = if group_memory.is_empty() {
        sender_memory
    } else if sender_memory.is_empty() {
        group_memory
    } else {
        format!("{sender_memory}\n{group_memory}")
    };

    let session_toolbox = if msg.channel == "cli" || ctx.autonomy_level == AutonomyLevel::Full {
        ctx.dynamic_tools.toolbox_template.fork_session()
    } else {
        ctx.dynamic_tools
            .toolbox_template
            .fork_session_with_exclusions(ctx.non_cli_excluded_tools.as_ref())
    };
    let message_skills = crate::skills::load_skills_with_config(
        ctx.workspace_dir.as_ref(),
        ctx.prompt_config.as_ref(),
    );
    let mut history = vec![ChatMessage::system("")];
    history.extend(prior_turns);
    let use_streaming = target_channel
        .as_ref()
        .is_some_and(|ch| ch.supports_draft_updates());

    tracing::debug!(
        channel = %msg.channel,
        has_target_channel = target_channel.is_some(),
        use_streaming,
        supports_draft = target_channel.as_ref().map_or(false, |ch| ch.supports_draft_updates()),
        "Draft streaming decision"
    );

    let (delta_tx, delta_rx) = if use_streaming {
        let (tx, rx) = tokio::sync::mpsc::channel::<String>(64);
        (Some(tx), Some(rx))
    } else {
        (None, None)
    };

    let draft_message_id = if use_streaming {
        if let Some(channel) = target_channel.as_ref() {
            match channel
                .send_draft(
                    &SendMessage::new("...", &msg.reply_target).in_thread(msg.thread_ts.clone()),
                )
                .await
            {
                Ok(id) => id,
                Err(e) => {
                    tracing::debug!("Failed to send draft on {}: {e}", channel.name());
                    None
                }
            }
        } else {
            None
        }
    } else {
        None
    };

    let draft_updater = if let (Some(mut rx), Some(draft_id_ref), Some(channel_ref)) = (
        delta_rx,
        draft_message_id.as_deref(),
        target_channel.as_ref(),
    ) {
        let channel = Arc::clone(channel_ref);
        let reply_target = msg.reply_target.clone();
        let draft_id = draft_id_ref.to_string();
        Some(tokio::spawn(async move {
            let mut accumulated = String::new();
            while let Some(delta) = rx.recv().await {
                if delta == crate::agent::loop_::DRAFT_CLEAR_SENTINEL {
                    accumulated.clear();
                    continue;
                }
                accumulated.push_str(&delta);
                if let Err(e) = channel
                    .update_draft(&reply_target, &draft_id, &accumulated)
                    .await
                {
                    tracing::debug!("Draft update failed: {e}");
                }
            }
        }))
    } else {
        None
    };

    // React with 👀 to acknowledge the incoming message
    if ctx.ack_reactions {
        if let Some(channel) = target_channel.as_ref() {
            if let Err(e) = channel
                .add_reaction(&msg.reply_target, &msg.id, "\u{1F440}")
                .await
            {
                tracing::debug!("Failed to add reaction: {e}");
            }
        }
    }

    let typing_cancellation = target_channel.as_ref().map(|_| CancellationToken::new());
    let typing_task = match (target_channel.as_ref(), typing_cancellation.as_ref()) {
        (Some(channel), Some(token)) => Some(spawn_scoped_typing_task(
            Arc::clone(channel),
            msg.reply_target.clone(),
            token.clone(),
        )),
        _ => None,
    };

    // Wrap observer to forward tool events as live thread messages
    let (notify_tx, mut notify_rx) = tokio::sync::mpsc::unbounded_channel::<String>();
    let notify_observer: Arc<ChannelNotifyObserver> = Arc::new(ChannelNotifyObserver {
        inner: Arc::clone(&ctx.observer),
        tx: notify_tx,
        tools_used: AtomicBool::new(false),
    });
    let notify_observer_flag = Arc::clone(&notify_observer);
    let notify_channel = target_channel.clone();
    let notify_reply_target = msg.reply_target.clone();
    let notify_thread_root = followup_thread_id(&msg);
    let notify_task = if msg.channel == "cli" || !ctx.show_tool_calls {
        Some(tokio::spawn(async move {
            while notify_rx.recv().await.is_some() {}
        }))
    } else {
        Some(tokio::spawn(async move {
            let thread_ts = notify_thread_root;
            while let Some(text) = notify_rx.recv().await {
                if let Some(ref ch) = notify_channel {
                    let _ = ch
                        .send(
                            &SendMessage::new(&text, &notify_reply_target)
                                .in_thread(thread_ts.clone()),
                        )
                        .await;
                }
            }
        }))
    };

    // Record history length before tool loop so we can extract tool context after.
    let history_len_before_tools = history.len();

    enum LlmExecutionResult {
        Completed(Result<Result<String, anyhow::Error>, tokio::time::error::Elapsed>),
        Cancelled,
    }

    let model_switch_callback = ctx.model_switch_state.callback();
    let scale_cap = ctx
        .pacing
        .message_timeout_scale_max
        .unwrap_or(CHANNEL_MESSAGE_TIMEOUT_SCALE_CAP);
    let timeout_budget_secs = channel_message_timeout_budget_secs_with_cap(
        ctx.message_timeout_secs,
        ctx.max_tool_iterations,
        scale_cap,
    );
    let cost_tracking_context = ctx.cost_tracking.clone().map(|state| {
        crate::agent::loop_::ToolLoopCostTrackingContext::new(state.tracker, state.prices)
    });
    let excluded_tools = if msg.channel == "cli" || ctx.autonomy_level == AutonomyLevel::Full {
        Vec::new()
    } else {
        ctx.non_cli_excluded_tools.as_ref().clone()
    };
    let llm_call_start = Instant::now();
    #[allow(clippy::cast_possible_truncation)]
    let elapsed_before_llm_ms = started_at.elapsed().as_millis() as u64;
    tracing::info!(elapsed_before_llm_ms, "⏱ Starting LLM call");
    let llm_result = loop {
        let native_tools = active_provider.supports_native_tools();
        let prompt_renderer = || {
            let base_prompt = render_runtime_system_prompt(RuntimeSystemPromptContext {
                workspace_dir: ctx.workspace_dir.as_ref(),
                model_name: route.model.as_str(),
                tool_desc_catalog: ctx.dynamic_tools.tool_descs.as_ref(),
                skills: &message_skills,
                identity_config: Some(&ctx.prompt_config.identity),
                bootstrap_max_chars: ctx.dynamic_tools.bootstrap_max_chars,
                autonomy_config: Some(&ctx.prompt_config.autonomy),
                native_tools,
                skills_prompt_mode: ctx.prompt_config.skills.prompt_injection_mode,
                tool_descriptions: ctx.dynamic_tools.tool_descriptions.as_deref(),
                toolbox_manager: Some(&session_toolbox),
                tools_registry: ctx.tools_registry.as_ref(),
                activated_tools: ctx.activated_tools.as_ref(),
                excluded_tools: &excluded_tools,
                deferred_section: ctx.dynamic_tools.deferred_section.as_str(),
            });
            let mut prompt =
                build_channel_system_prompt(&base_prompt, &msg.channel, &msg.reply_target);
            if !memory_context.is_empty() {
                let _ = write!(prompt, "\n\n{memory_context}");
            }
            prompt
        };
        let loop_result = tokio::select! {
            () = cancellation_token.cancelled() => LlmExecutionResult::Cancelled,
            result = tokio::time::timeout(
                Duration::from_secs(timeout_budget_secs),
                crate::agent::loop_::TOOL_LOOP_COST_TRACKING_CONTEXT.scope(
                    cost_tracking_context.clone(),
                crate::agent::loop_::run_tool_call_loop_with_options(
                    active_provider.as_ref(),
                    &mut history,
                    ctx.tools_registry.as_ref(),
                    Some(&session_toolbox),
                    notify_observer.as_ref() as &dyn Observer,
                    route.provider.as_str(),
                    route.model.as_str(),
                    runtime_defaults.temperature,
                    true,
                    Some(&*ctx.approval_manager),
                    msg.channel.as_str(),
                    Some(msg.reply_target.as_str()),
                    &ctx.multimodal,
                    ctx.max_tool_iterations,
                    Some(cancellation_token.clone()),
                    delta_tx.clone(),
                    ctx.hooks.as_deref(),
                    &excluded_tools,
                    ctx.tool_call_dedup_exempt.as_ref(),
                    ctx.activated_tools.as_ref(),
                    Some(model_switch_callback.clone()),
                    Some(&prompt_renderer),
                    &ctx.pacing,
                ),
                ),
            ) => LlmExecutionResult::Completed(result),
        };

        // Handle model switch: re-create the provider and retry
        if let LlmExecutionResult::Completed(Ok(Err(ref e))) = loop_result {
            if let Some((new_provider, new_model)) = is_model_switch_requested(e) {
                tracing::info!(
                    "Model switch requested, switching from {} {} to {} {}",
                    route.provider,
                    route.model,
                    new_provider,
                    new_model
                );

                match provider::create_resilient_provider_nonblocking(
                    &new_provider,
                    ctx.api_key.clone(),
                    ctx.api_url.clone(),
                    ctx.reliability.as_ref().clone(),
                    ctx.provider_runtime_options.clone(),
                )
                .await
                {
                    Ok(new_prov) => {
                        active_provider = Arc::from(new_prov);
                        route.provider = new_provider;
                        route.model = new_model;
                        ctx.model_switch_state.clear();

                        ctx.observer.record_event(&ObserverEvent::AgentStart {
                            provider: route.provider.clone(),
                            model: route.model.clone(),
                        });

                        continue;
                    }
                    Err(err) => {
                        tracing::error!("Failed to create provider after model switch: {err}");
                        ctx.model_switch_state.clear();
                        // Fall through with the original error
                    }
                }
            }
        }

        break loop_result;
    };

    if let Some(handle) = draft_updater {
        let _ = handle.await;
    }

    // Thread the final reply only if tools were used (multi-message response)
    if notify_observer_flag.tools_used.load(Ordering::Relaxed) && msg.channel != "cli" {
        msg.thread_ts = followup_thread_id(&msg);
    }
    // Drop the notify sender so the forwarder task finishes
    drop(notify_observer);
    drop(notify_observer_flag);
    if let Some(handle) = notify_task {
        let _ = handle.await;
    }

    #[allow(clippy::cast_possible_truncation)]
    let llm_call_ms = llm_call_start.elapsed().as_millis() as u64;
    #[allow(clippy::cast_possible_truncation)]
    let total_ms = started_at.elapsed().as_millis() as u64;
    tracing::info!(llm_call_ms, total_ms, "⏱ LLM call completed");

    if let Some(token) = typing_cancellation.as_ref() {
        token.cancel();
    }
    if let Some(handle) = typing_task {
        log_worker_join_result(handle.await);
    }

    let reaction_done_emoji = match &llm_result {
        LlmExecutionResult::Completed(Ok(Ok(_))) => "\u{2705}", // ✅
        _ => "\u{26A0}\u{FE0F}",                                // ⚠️
    };

    match llm_result {
        LlmExecutionResult::Cancelled => {
            tracing::info!(
                channel = %msg.channel,
                sender = %msg.sender,
                "Cancelled in-flight channel request due to newer message"
            );
            runtime_trace::record_event(
                "channel_message_cancelled",
                Some(msg.channel.as_str()),
                Some(route.provider.as_str()),
                Some(route.model.as_str()),
                None,
                Some(false),
                Some("cancelled due to newer inbound message"),
                serde_json::json!({
                    "sender": msg.sender,
                    "elapsed_ms": started_at.elapsed().as_millis(),
                }),
            );
            if let (Some(channel), Some(draft_id)) =
                (target_channel.as_ref(), draft_message_id.as_deref())
            {
                if let Err(err) = channel.cancel_draft(&msg.reply_target, draft_id).await {
                    tracing::debug!("Failed to cancel draft on {}: {err}", channel.name());
                }
            }
        }
        LlmExecutionResult::Completed(Ok(Ok(response))) => {
            // ── Hook: on_message_sending (modifying) ─────────
            let mut outbound_response = response;
            if let Some(hooks) = &ctx.hooks {
                match hooks
                    .run_on_message_sending(
                        msg.channel.clone(),
                        msg.reply_target.clone(),
                        outbound_response.clone(),
                    )
                    .await
                {
                    crate::hooks::HookResult::Cancel(reason) => {
                        tracing::info!(%reason, "outgoing message suppressed by hook");
                        return;
                    }
                    crate::hooks::HookResult::Continue((
                        hook_channel,
                        hook_recipient,
                        mut modified_content,
                    )) => {
                        if hook_channel != msg.channel || hook_recipient != msg.reply_target {
                            tracing::warn!(
                                from_channel = %msg.channel,
                                from_recipient = %msg.reply_target,
                                to_channel = %hook_channel,
                                to_recipient = %hook_recipient,
                                "on_message_sending attempted to rewrite channel routing; only content mutation is applied"
                            );
                        }

                        let modified_len = modified_content.chars().count();
                        if modified_len > CHANNEL_HOOK_MAX_OUTBOUND_CHARS {
                            tracing::warn!(
                                limit = CHANNEL_HOOK_MAX_OUTBOUND_CHARS,
                                attempted = modified_len,
                                "hook-modified outbound content exceeded limit; truncating"
                            );
                            modified_content = truncate_with_ellipsis(
                                &modified_content,
                                CHANNEL_HOOK_MAX_OUTBOUND_CHARS,
                            );
                        }

                        if modified_content != outbound_response {
                            tracing::info!(
                                channel = %msg.channel,
                                sender = %msg.sender,
                                before_len = outbound_response.chars().count(),
                                after_len = modified_content.chars().count(),
                                "outgoing message content modified by hook"
                            );
                        }

                        outbound_response = modified_content;
                    }
                }
            }

            let sanitized_response =
                sanitize_channel_response(&outbound_response, ctx.tools_registry.as_ref());
            let delivered_response = if sanitized_response.is_empty()
                && !outbound_response.trim().is_empty()
            {
                "I encountered malformed tool-call output and could not produce a safe reply. Please try again.".to_string()
            } else {
                sanitized_response
            };

            runtime_trace::record_event(
                "channel_message_outbound",
                Some(msg.channel.as_str()),
                Some(route.provider.as_str()),
                Some(route.model.as_str()),
                None,
                Some(true),
                None,
                serde_json::json!({
                    "sender": msg.sender,
                    "elapsed_ms": started_at.elapsed().as_millis(),
                    "response": scrub_credentials(&delivered_response),
                }),
            );

            // Extract condensed tool-use context from the history messages
            // added during run_tool_call_loop, so the LLM retains awareness
            // of what it did on subsequent turns.
            let tool_summary = extract_tool_context_summary(&history, history_len_before_tools);
            let history_response = if tool_summary.is_empty() || msg.channel == "telegram" {
                delivered_response.clone()
            } else {
                format!("{tool_summary}\n{delivered_response}")
            };

            append_sender_turn(
                ctx.as_ref(),
                &history_key,
                ChatMessage::assistant(&history_response),
            );

            // Fire-and-forget LLM-driven memory consolidation.
            if ctx.auto_save_memory && msg.content.chars().count() >= AUTOSAVE_MIN_MESSAGE_CHARS {
                let provider = Arc::clone(&ctx.provider);
                let model = ctx.model.to_string();
                let memory = Arc::clone(&ctx.memory);
                let user_msg = msg.content.clone();
                let assistant_resp = delivered_response.clone();
                tokio::spawn(async move {
                    if let Err(e) = crate::memory::consolidation::consolidate_turn(
                        provider.as_ref(),
                        &model,
                        memory.as_ref(),
                        &user_msg,
                        &assistant_resp,
                    )
                    .await
                    {
                        tracing::debug!("Memory consolidation skipped: {e}");
                    }
                });
            }

            println!(
                "  🤖 Reply ({}ms): {}",
                started_at.elapsed().as_millis(),
                truncate_with_ellipsis(&delivered_response, 80)
            );
            if let Some(channel) = target_channel.as_ref() {
                if let Some(ref draft_id) = draft_message_id {
                    if let Err(e) = channel
                        .finalize_draft(&msg.reply_target, draft_id, &delivered_response)
                        .await
                    {
                        tracing::warn!("Failed to finalize draft: {e}; sending as new message");
                        let _ = channel
                            .send(
                                &SendMessage::new(&delivered_response, &msg.reply_target)
                                    .in_thread(msg.thread_ts.clone()),
                            )
                            .await;
                    }
                } else if let Err(e) = channel
                    .send(
                        &SendMessage::new(&delivered_response, &msg.reply_target)
                            .in_thread(msg.thread_ts.clone()),
                    )
                    .await
                {
                    eprintln!("  ❌ Failed to reply on {}: {e}", channel.name());
                }
            }
        }
        LlmExecutionResult::Completed(Ok(Err(e))) => {
            if crate::agent::loop_::is_tool_loop_cancelled(&e) || cancellation_token.is_cancelled()
            {
                tracing::info!(
                    channel = %msg.channel,
                    sender = %msg.sender,
                    "Cancelled in-flight channel request due to newer message"
                );
                runtime_trace::record_event(
                    "channel_message_cancelled",
                    Some(msg.channel.as_str()),
                    Some(route.provider.as_str()),
                    Some(route.model.as_str()),
                    None,
                    Some(false),
                    Some("cancelled during tool-call loop"),
                    serde_json::json!({
                        "sender": msg.sender,
                        "elapsed_ms": started_at.elapsed().as_millis(),
                    }),
                );
                if let (Some(channel), Some(draft_id)) =
                    (target_channel.as_ref(), draft_message_id.as_deref())
                {
                    if let Err(err) = channel.cancel_draft(&msg.reply_target, draft_id).await {
                        tracing::debug!("Failed to cancel draft on {}: {err}", channel.name());
                    }
                }
            } else if is_context_window_overflow_error(&e) {
                let compacted = compact_sender_history(ctx.as_ref(), &history_key);
                let error_text = if compacted {
                    "⚠️ Context window exceeded for this conversation. I compacted recent history and kept the latest context. Please resend your last message."
                } else {
                    "⚠️ Context window exceeded for this conversation. Please resend your last message."
                };
                eprintln!(
                    "  ⚠️ Context window exceeded after {}ms; sender history compacted={}",
                    started_at.elapsed().as_millis(),
                    compacted
                );
                runtime_trace::record_event(
                    "channel_message_error",
                    Some(msg.channel.as_str()),
                    Some(route.provider.as_str()),
                    Some(route.model.as_str()),
                    None,
                    Some(false),
                    Some("context window exceeded"),
                    serde_json::json!({
                        "sender": msg.sender,
                        "elapsed_ms": started_at.elapsed().as_millis(),
                        "history_compacted": compacted,
                    }),
                );
                if let Some(channel) = target_channel.as_ref() {
                    if let Some(ref draft_id) = draft_message_id {
                        let _ = channel
                            .finalize_draft(&msg.reply_target, draft_id, error_text)
                            .await;
                    } else {
                        let _ = channel
                            .send(
                                &SendMessage::new(error_text, &msg.reply_target)
                                    .in_thread(msg.thread_ts.clone()),
                            )
                            .await;
                    }
                }
            } else {
                eprintln!(
                    "  ❌ LLM error after {}ms: {e}",
                    started_at.elapsed().as_millis()
                );
                let safe_error = providers::sanitize_api_error(&e.to_string());
                runtime_trace::record_event(
                    "channel_message_error",
                    Some(msg.channel.as_str()),
                    Some(route.provider.as_str()),
                    Some(route.model.as_str()),
                    None,
                    Some(false),
                    Some(&safe_error),
                    serde_json::json!({
                        "sender": msg.sender,
                        "elapsed_ms": started_at.elapsed().as_millis(),
                    }),
                );
                let should_rollback_user_turn = e
                    .downcast_ref::<providers::ProviderCapabilityError>()
                    .is_some_and(|capability| capability.capability.eq_ignore_ascii_case("vision"));
                let rolled_back = should_rollback_user_turn
                    && rollback_orphan_user_turn(ctx.as_ref(), &history_key, &msg.content);

                if !rolled_back {
                    // Close the orphan user turn so subsequent messages don't
                    // inherit this failed request as unfinished context.
                    append_sender_turn(
                        ctx.as_ref(),
                        &history_key,
                        ChatMessage::assistant("[Task failed — not continuing this request]"),
                    );
                }
                if let Some(channel) = target_channel.as_ref() {
                    if let Some(ref draft_id) = draft_message_id {
                        let _ = channel
                            .finalize_draft(&msg.reply_target, draft_id, &format!("⚠️ Error: {e}"))
                            .await;
                    } else {
                        let _ = channel
                            .send(
                                &SendMessage::new(format!("⚠️ Error: {e}"), &msg.reply_target)
                                    .in_thread(msg.thread_ts.clone()),
                            )
                            .await;
                    }
                }
            }
        }
        LlmExecutionResult::Completed(Err(_)) => {
            let timeout_msg = format!(
                "LLM response timed out after {}s (base={}s, max_tool_iterations={})",
                timeout_budget_secs, ctx.message_timeout_secs, ctx.max_tool_iterations
            );
            runtime_trace::record_event(
                "channel_message_timeout",
                Some(msg.channel.as_str()),
                Some(route.provider.as_str()),
                Some(route.model.as_str()),
                None,
                Some(false),
                Some(&timeout_msg),
                serde_json::json!({
                    "sender": msg.sender,
                    "elapsed_ms": started_at.elapsed().as_millis(),
                }),
            );
            eprintln!(
                "  ❌ {} (elapsed: {}ms)",
                timeout_msg,
                started_at.elapsed().as_millis()
            );
            // Close the orphan user turn so subsequent messages don't
            // inherit this timed-out request as unfinished context.
            append_sender_turn(
                ctx.as_ref(),
                &history_key,
                ChatMessage::assistant("[Task timed out — not continuing this request]"),
            );
            if let Some(channel) = target_channel.as_ref() {
                let error_text =
                    "⚠️ Request timed out while waiting for the model. Please try again.";
                if let Some(ref draft_id) = draft_message_id {
                    let _ = channel
                        .finalize_draft(&msg.reply_target, draft_id, error_text)
                        .await;
                } else {
                    let _ = channel
                        .send(
                            &SendMessage::new(error_text, &msg.reply_target)
                                .in_thread(msg.thread_ts.clone()),
                        )
                        .await;
                }
            }
        }
    }

    // Swap 👀 → ✅ (or ⚠️ on error) to signal processing is complete
    if ctx.ack_reactions {
        if let Some(channel) = target_channel.as_ref() {
            let _ = channel
                .remove_reaction(&msg.reply_target, &msg.id, "\u{1F440}")
                .await;
            let _ = channel
                .add_reaction(&msg.reply_target, &msg.id, reaction_done_emoji)
                .await;
        }
    }
}

