//! Conversation history management helpers for channel sessions.
//!
//! Extracted from the parent module to keep history-related logic isolated
//! and easier to test independently.

use crate::providers::ChatMessage;
use crate::util::truncate_with_ellipsis;

use super::{
    CHANNEL_HISTORY_COMPACT_CONTENT_CHARS, CHANNEL_HISTORY_COMPACT_KEEP_MESSAGES,
    ChannelRuntimeContext, MAX_CHANNEL_HISTORY, normalize_cached_channel_turns,
};

pub(super) fn compact_sender_history(ctx: &ChannelRuntimeContext, sender_key: &str) -> bool {
    let mut histories = ctx
        .conversation_histories
        .lock()
        .unwrap_or_else(|e| e.into_inner());

    let Some(turns) = histories.get_mut(sender_key) else {
        return false;
    };

    if turns.is_empty() {
        return false;
    }

    let keep_from = turns
        .len()
        .saturating_sub(CHANNEL_HISTORY_COMPACT_KEEP_MESSAGES);
    let mut compacted = normalize_cached_channel_turns(turns[keep_from..].to_vec());

    for turn in &mut compacted {
        if turn.content.chars().count() > CHANNEL_HISTORY_COMPACT_CONTENT_CHARS {
            turn.content =
                truncate_with_ellipsis(&turn.content, CHANNEL_HISTORY_COMPACT_CONTENT_CHARS);
        }
    }

    if compacted.is_empty() {
        turns.clear();
        return false;
    }

    *turns = compacted;
    true
}

/// Proactively trim conversation turns so that the total estimated character
/// count stays within the given `budget`.  Drops the oldest turns first, but
/// always preserves the most recent turn (the current user message).  Returns
/// the number of turns dropped.
pub(super) fn proactive_trim_turns(turns: &mut Vec<ChatMessage>, budget: usize) -> usize {
    let total_chars: usize = turns.iter().map(|t| t.content.chars().count()).sum();
    if total_chars <= budget || turns.len() <= 1 {
        return 0;
    }

    let mut excess = total_chars.saturating_sub(budget);
    let mut drop_count = 0;

    // Walk from the oldest turn forward, but never drop the very last turn.
    while excess > 0 && drop_count < turns.len().saturating_sub(1) {
        excess = excess.saturating_sub(turns[drop_count].content.chars().count());
        drop_count += 1;
    }

    if drop_count > 0 {
        turns.drain(..drop_count);
    }
    drop_count
}

pub(super) fn append_sender_turn(ctx: &ChannelRuntimeContext, sender_key: &str, turn: ChatMessage) {
    // Persist to JSONL before adding to in-memory history.
    if let Some(ref store) = ctx.session_store {
        if let Err(e) = store.append(sender_key, &turn) {
            tracing::warn!("Failed to persist session turn: {e}");
        }
    }

    let mut histories = ctx
        .conversation_histories
        .lock()
        .unwrap_or_else(|e| e.into_inner());
    let turns = histories.entry(sender_key.to_string()).or_default();
    turns.push(turn);
    while turns.len() > MAX_CHANNEL_HISTORY {
        turns.remove(0);
    }
}

pub(super) fn rollback_orphan_user_turn(
    ctx: &ChannelRuntimeContext,
    sender_key: &str,
    expected_content: &str,
) -> bool {
    let mut histories = ctx
        .conversation_histories
        .lock()
        .unwrap_or_else(|e| e.into_inner());
    let Some(turns) = histories.get_mut(sender_key) else {
        return false;
    };

    let should_pop = turns
        .last()
        .is_some_and(|turn| turn.role == "user" && turn.content == expected_content);
    if !should_pop {
        return false;
    }

    turns.pop();
    if turns.is_empty() {
        histories.remove(sender_key);
    }

    // Also remove the orphan turn from the persisted JSONL session store so
    // it doesn't resurface after a daemon restart (fixes #3674).
    if let Some(ref store) = ctx.session_store {
        if let Err(e) = store.remove_last(sender_key) {
            tracing::warn!("Failed to rollback session store entry: {e}");
        }
    }

    true
}
