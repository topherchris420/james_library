//! Channel subsystem for messaging platform integrations.
//!
//! This module provides the multi-channel messaging infrastructure that connects
//! R.A.I.N. to external platforms. Each channel implements the [`Channel`] trait
//! defined in [`traits`], which provides a uniform interface for sending messages,
//! listening for incoming messages, health checking, and typing indicators.
//!
//! Channels are instantiated by [`start_channels`] based on the runtime configuration.
//! The subsystem manages per-sender conversation history, concurrent message processing
//! with configurable parallelism, and exponential-backoff reconnection for resilience.
//!
//! # Extension
//!
//! To add a new channel, implement [`Channel`] in a new submodule and wire it into
//! [`start_channels`]. See `AGENTS.md` §7.2 for the full change playbook.

pub mod bluesky;
pub mod clawdtalk;
pub mod cli;
pub mod dingtalk;
pub mod discord;
mod dispatch;
pub mod email_channel;
mod factory;
mod health;
mod history;
pub mod imessage;
pub mod irc;
#[cfg(feature = "channel-lark")]
pub mod lark;
pub mod linq;
#[cfg(feature = "channel-matrix")]
pub mod matrix;
pub mod mattermost;
pub mod media_pipeline;
pub mod mochat;
pub mod nextcloud_talk;
#[cfg(feature = "channel-nostr")]
pub mod nostr;
pub mod notion;
pub mod qq;
pub mod reddit;
mod registry;
pub(crate) mod runtime_state;
pub(crate) mod sanitize;
pub mod session_backend;
pub mod session_sqlite;
pub mod session_store;
pub mod signal;
pub mod slack;
mod startup;
pub mod telegram;
pub mod traits;

pub(crate) mod processor;
pub(crate) use processor::process_channel_message;

pub(crate) mod prompt;
pub use prompt::{
    build_system_prompt, build_system_prompt_with_mode, build_system_prompt_with_mode_and_autonomy,
};

// Re-exports from prompt for internal usage
use prompt::bind_telegram_identity;

pub(crate) mod provider;
pub mod transcription;
pub mod tts;
pub mod twitter;
pub mod wati;
pub mod webhook;
pub mod wecom;
pub mod whatsapp;
#[cfg(feature = "whatsapp-web")]
pub mod whatsapp_storage;
#[cfg(feature = "whatsapp-web")]
pub mod whatsapp_web;

pub use bluesky::BlueskyChannel;
pub use clawdtalk::{ClawdTalkChannel, ClawdTalkConfig};
pub use cli::CliChannel;
pub use dingtalk::DingTalkChannel;
pub use discord::DiscordChannel;
pub use email_channel::EmailChannel;
pub use imessage::IMessageChannel;
pub use irc::IrcChannel;
#[cfg(feature = "channel-lark")]
pub use lark::LarkChannel;
pub use linq::LinqChannel;
#[cfg(feature = "channel-matrix")]
pub use matrix::MatrixChannel;
pub use mattermost::MattermostChannel;
pub use mochat::MochatChannel;
pub use nextcloud_talk::NextcloudTalkChannel;
#[cfg(feature = "channel-nostr")]
pub use nostr::NostrChannel;
pub use notion::NotionChannel;
pub use qq::QQChannel;
pub use reddit::RedditChannel;
pub use signal::SignalChannel;
pub use slack::SlackChannel;
pub use telegram::TelegramChannel;
pub use traits::{Channel, SendMessage};
#[allow(unused_imports)]
pub use tts::{TtsManager, TtsProvider};
pub use twitter::TwitterChannel;
pub use wati::WatiChannel;
pub use webhook::WebhookChannel;
pub use wecom::WeComChannel;
pub use whatsapp::WhatsAppChannel;
#[cfg(feature = "whatsapp-web")]
pub use whatsapp_web::WhatsAppWebChannel;

use crate::agent::loop_::{
    ModelSwitchState, RuntimeSystemPromptContext, build_runtime_toolbox_template,
    build_tool_instructions, is_model_switch_requested, load_runtime_agent_manifest,
    render_runtime_system_prompt, scrub_credentials,
};
use crate::approval::ApprovalManager;
use crate::config::Config;
use crate::i18n::ToolDescriptions;
use crate::memory::{self, Memory};
use crate::observability::traits::{ObserverEvent, ObserverMetric};
use crate::observability::{self, Observer};
use crate::providers::{self, ChatMessage, Provider};
use crate::runtime;
use crate::security::{AutonomyLevel, SecurityPolicy};
use crate::tools::{self, Tool};
use crate::util::truncate_with_ellipsis;
use anyhow::{Context, Result};
use portable_atomic::{AtomicU64, Ordering};
use serde::Deserialize;
use std::collections::{HashMap, HashSet};
use std::fmt::Write;
use std::path::PathBuf;
use std::process::Command;
use std::sync::atomic::AtomicBool;
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tokio_util::sync::CancellationToken;

use self::dispatch::run_message_dispatch_loop;
#[cfg(test)]
use self::factory::build_channel_by_id;
use self::factory::send_channel_message;
use self::health::{ChannelHealthState, classify_health_result};
use self::runtime_state::{
    RuntimeConfigState, config_file_stamp, interruption_scope_key, resolved_default_model, resolved_default_provider,
    runtime_config_store, runtime_defaults_from_config,
};
use self::sanitize::strip_tool_call_tags;

/// Observer wrapper that forwards tool-call events to a channel sender
/// for real-time threaded notifications.
struct ChannelNotifyObserver {
    inner: Arc<dyn Observer>,
    tx: tokio::sync::mpsc::UnboundedSender<String>,
    tools_used: AtomicBool,
}

impl Observer for ChannelNotifyObserver {
    fn record_event(&self, event: &ObserverEvent) {
        if let ObserverEvent::ToolCallStart { tool, arguments } = event {
            self.tools_used.store(true, Ordering::Relaxed);
            let detail = match arguments {
                Some(args) if !args.is_empty() => {
                    if let Ok(v) = serde_json::from_str::<serde_json::Value>(args) {
                        if let Some(cmd) = v.get("command").and_then(|c| c.as_str()) {
                            format!(": `{}`", truncate_with_ellipsis(cmd, 200))
                        } else if let Some(q) = v.get("query").and_then(|c| c.as_str()) {
                            format!(": {}", truncate_with_ellipsis(q, 200))
                        } else if let Some(p) = v.get("path").and_then(|c| c.as_str()) {
                            format!(": {p}")
                        } else if let Some(u) = v.get("url").and_then(|c| c.as_str()) {
                            format!(": {u}")
                        } else {
                            let s = args.to_string();
                            format!(": {}", truncate_with_ellipsis(&s, 120))
                        }
                    } else {
                        let s = args.to_string();
                        format!(": {}", truncate_with_ellipsis(&s, 120))
                    }
                }
                _ => String::new(),
            };
            let _ = self.tx.send(format!("\u{1F527} `{tool}`{detail}"));
        }
        self.inner.record_event(event);
    }
    fn record_metric(&self, metric: &ObserverMetric) {
        self.inner.record_metric(metric);
    }
    fn flush(&self) {
        self.inner.flush();
    }
    fn name(&self) -> &str {
        "channel-notify"
    }
    fn as_any(&self) -> &dyn std::any::Any {
        self
    }
}

/// Per-sender conversation history for channel messages.
type ConversationHistoryMap = Arc<Mutex<HashMap<String, Vec<ChatMessage>>>>;
/// Senders that requested `/new` and must force a fresh prompt on their next message.
type PendingNewSessionSet = Arc<Mutex<HashSet<String>>>;
/// Maximum history messages to keep per sender.
const MAX_CHANNEL_HISTORY: usize = 50;
/// Minimum user-message length (in chars) for auto-save to memory.
/// Messages shorter than this (e.g. "ok", "thanks") are not stored,
/// reducing noise in memory recall.
const AUTOSAVE_MIN_MESSAGE_CHARS: usize = 20;

/// Maximum characters per injected workspace file (matches `OpenClaw` default).
const BOOTSTRAP_MAX_CHARS: usize = 20_000;

const DEFAULT_CHANNEL_INITIAL_BACKOFF_SECS: u64 = 2;
const DEFAULT_CHANNEL_MAX_BACKOFF_SECS: u64 = 60;
const MIN_CHANNEL_MESSAGE_TIMEOUT_SECS: u64 = 30;
/// Default timeout for processing a single channel message (LLM + tools).
/// Used as fallback when not configured in channels_config.message_timeout_secs.
const CHANNEL_MESSAGE_TIMEOUT_SECS: u64 = 300;
/// Cap timeout scaling so large max_tool_iterations values do not create unbounded waits.
const CHANNEL_MESSAGE_TIMEOUT_SCALE_CAP: u64 = 4;
const CHANNEL_PARALLELISM_PER_CHANNEL: usize = 4;
const CHANNEL_MIN_IN_FLIGHT_MESSAGES: usize = 8;
const CHANNEL_MAX_IN_FLIGHT_MESSAGES: usize = 64;
const CHANNEL_TYPING_REFRESH_INTERVAL_SECS: u64 = 4;
const CHANNEL_HEALTH_HEARTBEAT_SECS: u64 = 30;
const MODEL_CACHE_FILE: &str = "models_cache.json";
const MODEL_CACHE_PREVIEW_LIMIT: usize = 10;
const MEMORY_CONTEXT_MAX_ENTRIES: usize = 4;
const MEMORY_CONTEXT_ENTRY_MAX_CHARS: usize = 800;
const MEMORY_CONTEXT_MAX_CHARS: usize = 4_000;
const CHANNEL_HISTORY_COMPACT_KEEP_MESSAGES: usize = 12;
const CHANNEL_HISTORY_COMPACT_CONTENT_CHARS: usize = 600;
/// Proactive context-window budget in estimated characters (~4 chars/token).
/// When the total character count of conversation history exceeds this limit,
/// older turns are dropped before the request is sent to the provider,
/// preventing context-window-exceeded errors.  Set conservatively below
/// common context windows (128 k tokens ≈ 512 k chars) to leave room for
/// system prompt, memory context, and model output.
const PROACTIVE_CONTEXT_BUDGET_CHARS: usize = 400_000;
/// Guardrail for hook-modified outbound channel content.
const CHANNEL_HOOK_MAX_OUTBOUND_CHARS: usize = 20_000;

use provider::ProviderCacheMap;
type RouteSelectionMap = Arc<Mutex<HashMap<String, ChannelRouteSelection>>>;

fn effective_channel_message_timeout_secs(configured: u64) -> u64 {
    configured.max(MIN_CHANNEL_MESSAGE_TIMEOUT_SECS)
}

fn channel_message_timeout_budget_secs(
    message_timeout_secs: u64,
    max_tool_iterations: usize,
) -> u64 {
    channel_message_timeout_budget_secs_with_cap(
        message_timeout_secs,
        max_tool_iterations,
        CHANNEL_MESSAGE_TIMEOUT_SCALE_CAP,
    )
}

fn channel_message_timeout_budget_secs_with_cap(
    message_timeout_secs: u64,
    max_tool_iterations: usize,
    scale_cap: u64,
) -> u64 {
    let iterations = max_tool_iterations.max(1) as u64;
    let scale = iterations.min(scale_cap);
    message_timeout_secs.saturating_mul(scale)
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct ChannelRouteSelection {
    provider: String,
    model: String,
    /// Route-specific API key override. When set, this takes precedence over
    /// the global `api_key` in [`ChannelRuntimeContext`] when creating the
    /// provider for this route.
    api_key: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum ChannelRuntimeCommand {
    ShowProviders,
    SetProvider(String),
    ShowModel,
    SetModel(String),
    NewSession,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub(crate) struct ModelCacheState {
    entries: Vec<ModelCacheEntry>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub(crate) struct ModelCacheEntry {
    provider: String,
    models: Vec<String>,
}

const SYSTEMD_STATUS_ARGS: [&str; 3] = ["--user", "is-active", "R.A.I.N..service"];
const SYSTEMD_RESTART_ARGS: [&str; 3] = ["--user", "restart", "R.A.I.N..service"];
const OPENRC_STATUS_ARGS: [&str; 2] = ["R.A.I.N.", "status"];
const OPENRC_RESTART_ARGS: [&str; 2] = ["R.A.I.N.", "restart"];

#[derive(Clone, Copy)]
#[allow(clippy::struct_excessive_bools)]
struct InterruptOnNewMessageConfig {
    telegram: bool,
    slack: bool,
    discord: bool,
    mattermost: bool,
    matrix: bool,
}

impl InterruptOnNewMessageConfig {
    fn enabled_for_channel(self, channel: &str) -> bool {
        match channel {
            "telegram" => self.telegram,
            "slack" => self.slack,
            "discord" => self.discord,
            "mattermost" => self.mattermost,
            "matrix" => self.matrix,
            _ => false,
        }
    }
}

#[derive(Clone)]
struct ChannelCostTrackingState {
    tracker: Arc<crate::cost::CostTracker>,
    prices: Arc<HashMap<String, crate::config::schema::ModelPricing>>,
}

#[derive(Clone, Default)]
struct DynamicToolRuntimeState {
    toolbox_template: tools::ToolboxManager,
    tool_descs: Arc<Vec<(String, String)>>,
    tool_descriptions: Option<Arc<ToolDescriptions>>,
    deferred_section: Arc<String>,
    bootstrap_max_chars: Option<usize>,
}

#[derive(Clone)]
pub(crate) struct ChannelRuntimeContext {
    channels_by_name: Arc<HashMap<String, Arc<dyn Channel>>>,
    provider: Arc<dyn Provider>,
    default_provider: Arc<String>,
    prompt_config: Arc<crate::config::Config>,
    memory: Arc<dyn Memory>,
    tools_registry: Arc<Vec<Box<dyn Tool>>>,
    observer: Arc<dyn Observer>,
    system_prompt: Arc<String>,
    dynamic_tools: DynamicToolRuntimeState,
    model: Arc<String>,
    temperature: f64,
    auto_save_memory: bool,
    max_tool_iterations: usize,
    min_relevance_score: f64,
    conversation_histories: ConversationHistoryMap,
    pending_new_sessions: PendingNewSessionSet,
    provider_cache: ProviderCacheMap,
    route_overrides: RouteSelectionMap,
    api_key: Option<String>,
    api_url: Option<String>,
    reliability: Arc<crate::config::ReliabilityConfig>,
    provider_runtime_options: providers::ProviderRuntimeOptions,
    workspace_dir: Arc<PathBuf>,
    message_timeout_secs: u64,
    interrupt_on_new_message: InterruptOnNewMessageConfig,
    multimodal: crate::config::MultimodalConfig,
    hooks: Option<Arc<crate::hooks::HookRunner>>,
    non_cli_excluded_tools: Arc<Vec<String>>,
    autonomy_level: AutonomyLevel,
    tool_call_dedup_exempt: Arc<Vec<String>>,
    model_routes: Arc<Vec<crate::config::ModelRouteConfig>>,
    query_classification: crate::config::QueryClassificationConfig,
    ack_reactions: bool,
    show_tool_calls: bool,
    session_store: Option<Arc<session_store::SessionStore>>,
    /// Non-interactive approval manager for channel-driven runs.
    /// Enforces `auto_approve` / `always_ask` / supervised policy from
    /// `[autonomy]` config; auto-denies tools that would need interactive
    /// approval since no operator is present on channel runs.
    approval_manager: Arc<ApprovalManager>,
    activated_tools: Option<std::sync::Arc<std::sync::Mutex<crate::tools::ActivatedToolSet>>>,
    cost_tracking: Option<ChannelCostTrackingState>,
    pacing: crate::config::PacingConfig,
    model_switch_state: ModelSwitchState,
}

impl ChannelRuntimeContext {
    pub(crate) fn provider_manager(&self) -> provider::ChannelProviderManager {
        provider::ChannelProviderManager::new(
            Arc::clone(&self.provider),
            Arc::clone(&self.default_provider),
            self.api_key.clone(),
            Arc::clone(&self.provider_cache),
            (*self.reliability).clone(),
            self.provider_runtime_options.clone(),
            self.api_url.clone(),
        )
    }
}

#[derive(Clone)]
struct InFlightSenderTaskState {
    task_id: u64,
    cancellation: CancellationToken,
    completion: Arc<InFlightTaskCompletion>,
}

struct InFlightTaskCompletion {
    done: AtomicBool,
    notify: tokio::sync::Notify,
}

impl InFlightTaskCompletion {
    fn new() -> Self {
        Self {
            done: AtomicBool::new(false),
            notify: tokio::sync::Notify::new(),
        }
    }

    fn mark_done(&self) {
        self.done.store(true, Ordering::Release);
        self.notify.notify_waiters();
    }

    async fn wait(&self) {
        if self.done.load(Ordering::Acquire) {
            return;
        }
        self.notify.notified().await;
    }
}

/// Returns `true` when `content` is a `/stop` command (with optional `@botname` suffix).
/// Not gated on channel type — all non-CLI channels support `/stop`.
fn is_stop_command(content: &str) -> bool {
    let trimmed = content.trim();
    if !trimmed.starts_with('/') {
        return false;
    }
    let cmd = trimmed.split_whitespace().next().unwrap_or("");
    let base = cmd.split('@').next().unwrap_or(cmd);
    base.eq_ignore_ascii_case("/stop")
}

fn normalize_cached_channel_turns(turns: Vec<ChatMessage>) -> Vec<ChatMessage> {
    let mut normalized = Vec::with_capacity(turns.len());
    let mut expecting_user = true;

    for turn in turns {
        match (expecting_user, turn.role.as_str()) {
            (true, "user") => {
                normalized.push(turn);
                expecting_user = false;
            }
            (false, "assistant") => {
                normalized.push(turn);
                expecting_user = true;
            }
            // Interrupted channel turns can produce consecutive user messages
            // (no assistant persisted yet). Merge instead of dropping.
            (false, "user") | (true, "assistant") => {
                if let Some(last_turn) = normalized.last_mut() {
                    if !turn.content.is_empty() {
                        if !last_turn.content.is_empty() {
                            last_turn.content.push_str("\n\n");
                        }
                        last_turn.content.push_str(&turn.content);
                    }
                }
            }
            _ => {}
        }
    }

    normalized
}

/// Remove `<tool_result …>…</tool_result>` blocks (and a leading `[Tool results]`
/// header, if present) from a conversation-history entry so that stale tool
/// output is never presented to the LLM without the corresponding `<tool_call>`.
fn strip_tool_result_content(text: &str) -> String {
    static TOOL_RESULT_RE: std::sync::LazyLock<regex::Regex> = std::sync::LazyLock::new(|| {
        regex::Regex::new(r"(?s)<tool_result[^>]*>.*?</tool_result>").unwrap()
    });

    let cleaned = TOOL_RESULT_RE.replace_all(text, "");
    let cleaned = cleaned.trim();

    // If the only remaining content is the header, drop it entirely.
    if cleaned == "[Tool results]" || cleaned.is_empty() {
        return String::new();
    }

    cleaned.to_string()
}

fn spawn_supervised_listener(
    ch: Arc<dyn Channel>,
    tx: tokio::sync::mpsc::Sender<traits::ChannelMessage>,
    initial_backoff_secs: u64,
    max_backoff_secs: u64,
) -> tokio::task::JoinHandle<()> {
    spawn_supervised_listener_with_health_interval(
        ch,
        tx,
        initial_backoff_secs,
        max_backoff_secs,
        Duration::from_secs(CHANNEL_HEALTH_HEARTBEAT_SECS),
    )
}

fn spawn_supervised_listener_with_health_interval(
    ch: Arc<dyn Channel>,
    tx: tokio::sync::mpsc::Sender<traits::ChannelMessage>,
    initial_backoff_secs: u64,
    max_backoff_secs: u64,
    health_interval: Duration,
) -> tokio::task::JoinHandle<()> {
    let health_interval = if health_interval.is_zero() {
        Duration::from_secs(1)
    } else {
        health_interval
    };

    tokio::spawn(async move {
        let component = format!("channel:{}", ch.name());
        let mut backoff = initial_backoff_secs.max(1);
        let max_backoff = max_backoff_secs.max(backoff);

        loop {
            crate::health::mark_component_ok(&component);
            let mut health = tokio::time::interval(health_interval);
            health.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
            let result = {
                let listen_future = ch.listen(tx.clone());
                tokio::pin!(listen_future);

                loop {
                    tokio::select! {
                        _ = health.tick() => {
                            crate::health::mark_component_ok(&component);
                        }
                        result = &mut listen_future => break result,
                    }
                }
            };

            if tx.is_closed() {
                break;
            }

            match result {
                Ok(()) => {
                    tracing::warn!("Channel {} exited unexpectedly; restarting", ch.name());
                    crate::health::mark_component_error(&component, "listener exited unexpectedly");
                    // Clean exit — reset backoff since the listener ran successfully
                    backoff = initial_backoff_secs.max(1);
                }
                Err(e) => {
                    tracing::error!("Channel {} error: {e}; restarting", ch.name());
                    crate::health::mark_component_error(&component, e.to_string());
                }
            }

            crate::health::bump_component_restart(&component);
            tokio::time::sleep(Duration::from_secs(backoff)).await;
            // Double backoff AFTER sleeping so first error uses initial_backoff
            backoff = backoff.saturating_mul(2).min(max_backoff);
        }
    })
}

fn compute_max_in_flight_messages(channel_count: usize) -> usize {
    channel_count
        .saturating_mul(CHANNEL_PARALLELISM_PER_CHANNEL)
        .clamp(
            CHANNEL_MIN_IN_FLIGHT_MESSAGES,
            CHANNEL_MAX_IN_FLIGHT_MESSAGES,
        )
}

fn log_worker_join_result(result: Result<(), tokio::task::JoinError>) {
    if let Err(error) = result {
        tracing::error!("Channel message worker crashed: {error}");
    }
}

fn spawn_scoped_typing_task(
    channel: Arc<dyn Channel>,
    recipient: String,
    cancellation_token: CancellationToken,
) -> tokio::task::JoinHandle<()> {
    let stop_signal = cancellation_token;
    let refresh_interval = Duration::from_secs(CHANNEL_TYPING_REFRESH_INTERVAL_SECS);
    tokio::spawn(async move {
        let mut interval = tokio::time::interval(refresh_interval);
        interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);

        loop {
            tokio::select! {
                () = stop_signal.cancelled() => break,
                _ = interval.tick() => {
                    if let Err(e) = channel.start_typing(&recipient).await {
                        tracing::debug!("Failed to start typing on {}: {e}", channel.name());
                    }
                }
            }
        }

        if let Err(e) = channel.stop_typing(&recipient).await {
            tracing::debug!("Failed to stop typing on {}: {e}", channel.name());
        }
    })
}

pub(crate) fn maybe_restart_managed_daemon_service() -> Result<bool> {
    if cfg!(target_os = "macos") {
        let home = directories::UserDirs::new()
            .map(|u| u.home_dir().to_path_buf())
            .context("Could not find home directory")?;
        let plist = home
            .join("Library")
            .join("LaunchAgents")
            .join("com.R.A.I.N..daemon.plist");
        if !plist.exists() {
            return Ok(false);
        }

        let list_output = Command::new("launchctl")
            .arg("list")
            .output()
            .context("Failed to query launchctl list")?;
        let listed = String::from_utf8_lossy(&list_output.stdout);
        if !listed.contains("com.R.A.I.N..daemon") {
            return Ok(false);
        }

        let _ = Command::new("launchctl")
            .args(["stop", "com.R.A.I.N..daemon"])
            .output();
        let start_output = Command::new("launchctl")
            .args(["start", "com.R.A.I.N..daemon"])
            .output()
            .context("Failed to start launchd daemon service")?;
        if !start_output.status.success() {
            let stderr = String::from_utf8_lossy(&start_output.stderr);
            anyhow::bail!("launchctl start failed: {}", stderr.trim());
        }

        return Ok(true);
    }

    if cfg!(target_os = "linux") {
        // OpenRC (system-wide) takes precedence over systemd (user-level)
        let openrc_init_script = PathBuf::from("/etc/init.d/R.A.I.N.");
        if openrc_init_script.exists() {
            if let Ok(status_output) = Command::new("rc-service").args(OPENRC_STATUS_ARGS).output()
            {
                // rc-service exits 0 if running, non-zero otherwise
                if status_output.status.success() {
                    let restart_output = Command::new("rc-service")
                        .args(OPENRC_RESTART_ARGS)
                        .output()
                        .context("Failed to restart OpenRC daemon service")?;
                    if !restart_output.status.success() {
                        let stderr = String::from_utf8_lossy(&restart_output.stderr);
                        anyhow::bail!("rc-service restart failed: {}", stderr.trim());
                    }
                    return Ok(true);
                }
            }
        }

        // Systemd (user-level)
        let home = directories::UserDirs::new()
            .map(|u| u.home_dir().to_path_buf())
            .context("Could not find home directory")?;
        let unit_path: PathBuf = home
            .join(".config")
            .join("systemd")
            .join("user")
            .join("R.A.I.N..service");
        if !unit_path.exists() {
            return Ok(false);
        }

        let active_output = Command::new("systemctl")
            .args(SYSTEMD_STATUS_ARGS)
            .output()
            .context("Failed to query systemd service state")?;
        let state = String::from_utf8_lossy(&active_output.stdout);
        if !state.trim().eq_ignore_ascii_case("active") {
            return Ok(false);
        }

        let restart_output = Command::new("systemctl")
            .args(SYSTEMD_RESTART_ARGS)
            .output()
            .context("Failed to restart systemd daemon service")?;
        if !restart_output.status.success() {
            let stderr = String::from_utf8_lossy(&restart_output.stderr);
            anyhow::bail!("systemctl restart failed: {}", stderr.trim());
        }

        return Ok(true);
    }

    Ok(false)
}

pub(crate) async fn handle_command(command: crate::ChannelCommands, config: &Config) -> Result<()> {
    match command {
        crate::ChannelCommands::Start => {
            anyhow::bail!("Start must be handled in main.rs (requires async runtime)")
        }
        crate::ChannelCommands::Doctor => {
            anyhow::bail!("Doctor must be handled in main.rs (requires async runtime)")
        }
        crate::ChannelCommands::List => {
            println!("Channels:");
            println!("  ✅ CLI (always available)");
            for (channel, configured) in config.channels_config.channels() {
                println!(
                    "  {} {}",
                    if configured { "✅" } else { "❌" },
                    channel.name()
                );
            }
            // Notion is a top-level config section, not part of ChannelsConfig
            {
                let notion_configured =
                    config.notion.enabled && !config.notion.database_id.trim().is_empty();
                println!("  {} Notion", if notion_configured { "✅" } else { "❌" });
            }
            if !cfg!(feature = "channel-matrix") {
                println!(
                    "  ℹ️ Matrix channel support is disabled in this build (enable `channel-matrix`)."
                );
            }
            if !cfg!(feature = "channel-lark") {
                println!(
                    "  ℹ️ Lark/Feishu channel support is disabled in this build (enable `channel-lark`)."
                );
            }
            println!("\nTo start channels: R.A.I.N. channel start");
            println!("To check health:    R.A.I.N. channel doctor");
            println!("To configure:      R.A.I.N. onboard");
            Ok(())
        }
        crate::ChannelCommands::Add {
            channel_type,
            config: _,
        } => {
            anyhow::bail!(
                "Channel type '{channel_type}' — use `R.A.I.N. onboard` to configure channels"
            );
        }
        crate::ChannelCommands::Remove { name } => {
            anyhow::bail!("Remove channel '{name}' — edit ~/.R.A.I.N./config.toml directly");
        }
        crate::ChannelCommands::BindTelegram { identity } => {
            Box::pin(bind_telegram_identity(config, &identity)).await
        }
        crate::ChannelCommands::Send {
            message,
            channel_id,
            recipient,
        } => send_channel_message(config, &channel_id, &recipient, &message).await,
    }
}

/// Build a single channel instance by config section name (e.g. "telegram").
struct ConfiguredChannel {
    display_name: &'static str,
    channel: Arc<dyn Channel>,
}

fn collect_configured_channels(
    config: &Config,
    matrix_skip_context: &str,
) -> Vec<ConfiguredChannel> {
    let _ = matrix_skip_context;
    let mut channels = Vec::new();

    if let Some(ref tg) = config.channels_config.telegram {
        let ack = tg
            .ack_reactions
            .unwrap_or(config.channels_config.ack_reactions);
        channels.push(ConfiguredChannel {
            display_name: "Telegram",
            channel: Arc::new(
                TelegramChannel::new(
                    tg.bot_token.clone(),
                    tg.allowed_users.clone(),
                    tg.mention_only,
                )
                .with_ack_reactions(ack)
                .with_streaming(tg.stream_mode, tg.draft_update_interval_ms)
                .with_transcription(config.transcription.clone())
                .with_tts(config.tts.clone())
                .with_workspace_dir(config.workspace_dir.clone())
                .with_proxy_url(tg.proxy_url.clone()),
            ),
        });
    }

    if let Some(ref dc) = config.channels_config.discord {
        channels.push(ConfiguredChannel {
            display_name: "Discord",
            channel: Arc::new(
                DiscordChannel::new(
                    dc.bot_token.clone(),
                    dc.guild_id.clone(),
                    dc.allowed_users.clone(),
                    dc.listen_to_bots,
                    dc.mention_only,
                )
                .with_proxy_url(dc.proxy_url.clone()),
            ),
        });
    }

    if let Some(ref sl) = config.channels_config.slack {
        channels.push(ConfiguredChannel {
            display_name: "Slack",
            channel: Arc::new(
                SlackChannel::new(
                    sl.bot_token.clone(),
                    sl.app_token.clone(),
                    sl.channel_id.clone(),
                    Vec::new(),
                    sl.allowed_users.clone(),
                )
                .with_thread_replies(sl.thread_replies.unwrap_or(true))
                .with_group_reply_policy(sl.mention_only, Vec::new())
                .with_workspace_dir(config.workspace_dir.clone())
                .with_proxy_url(sl.proxy_url.clone()),
            ),
        });
    }

    if let Some(ref mm) = config.channels_config.mattermost {
        channels.push(ConfiguredChannel {
            display_name: "Mattermost",
            channel: Arc::new(
                MattermostChannel::new(
                    mm.url.clone(),
                    mm.bot_token.clone(),
                    mm.channel_id.clone(),
                    mm.allowed_users.clone(),
                    mm.thread_replies.unwrap_or(true),
                    mm.mention_only.unwrap_or(false),
                )
                .with_proxy_url(mm.proxy_url.clone()),
            ),
        });
    }

    if let Some(ref im) = config.channels_config.imessage {
        channels.push(ConfiguredChannel {
            display_name: "iMessage",
            channel: Arc::new(IMessageChannel::new(im.allowed_contacts.clone())),
        });
    }

    #[cfg(feature = "channel-matrix")]
    if let Some(ref mx) = config.channels_config.matrix {
        channels.push(ConfiguredChannel {
            display_name: "Matrix",
            channel: Arc::new(MatrixChannel::new_with_session_hint_and_rain_dir(
                mx.homeserver.clone(),
                mx.access_token.clone(),
                mx.room_id.clone(),
                mx.allowed_users.clone(),
                mx.user_id.clone(),
                mx.device_id.clone(),
                config.config_path.parent().map(|path| path.to_path_buf()),
            )),
        });
    }

    #[cfg(not(feature = "channel-matrix"))]
    if config.channels_config.matrix.is_some() {
        tracing::warn!(
            "Matrix channel is configured but this build was compiled without `channel-matrix`; skipping Matrix {}.",
            matrix_skip_context
        );
    }

    if let Some(ref sig) = config.channels_config.signal {
        channels.push(ConfiguredChannel {
            display_name: "Signal",
            channel: Arc::new(
                SignalChannel::new(
                    sig.http_url.clone(),
                    sig.account.clone(),
                    sig.group_id.clone(),
                    sig.allowed_from.clone(),
                    sig.ignore_attachments,
                    sig.ignore_stories,
                )
                .with_proxy_url(sig.proxy_url.clone()),
            ),
        });
    }

    if let Some(ref wa) = config.channels_config.whatsapp {
        if wa.is_ambiguous_config() {
            tracing::warn!(
                "WhatsApp config has both phone_number_id and session_path set; preferring Cloud API mode. Remove one selector to avoid ambiguity."
            );
        }
        // Runtime negotiation: detect backend type from config
        match wa.backend_type() {
            "cloud" => {
                // Cloud API mode: requires phone_number_id, access_token, verify_token
                if wa.is_cloud_config() {
                    channels.push(ConfiguredChannel {
                        display_name: "WhatsApp",
                        channel: Arc::new(
                            WhatsAppChannel::new(
                                wa.access_token.clone().unwrap_or_default(),
                                wa.phone_number_id.clone().unwrap_or_default(),
                                wa.verify_token.clone().unwrap_or_default(),
                                wa.allowed_numbers.clone(),
                            )
                            .with_proxy_url(wa.proxy_url.clone()),
                        ),
                    });
                } else {
                    tracing::warn!(
                        "WhatsApp Cloud API configured but missing required fields (phone_number_id, access_token, verify_token)"
                    );
                }
            }
            "web" => {
                // Web mode: requires session_path
                #[cfg(feature = "whatsapp-web")]
                if wa.is_web_config() {
                    channels.push(ConfiguredChannel {
                        display_name: "WhatsApp",
                        channel: Arc::new(
                            WhatsAppWebChannel::new(
                                wa.session_path.clone().unwrap_or_default(),
                                wa.pair_phone.clone(),
                                wa.pair_code.clone(),
                                wa.allowed_numbers.clone(),
                                wa.mode.clone(),
                                wa.dm_policy.clone(),
                                wa.group_policy.clone(),
                                wa.self_chat_mode,
                            )
                            .with_transcription(config.transcription.clone())
                            .with_tts(config.tts.clone()),
                        ),
                    });
                } else {
                    tracing::warn!("WhatsApp Web configured but session_path not set");
                }
                #[cfg(not(feature = "whatsapp-web"))]
                {
                    tracing::warn!(
                        "WhatsApp Web backend requires 'whatsapp-web' feature. Enable with: cargo build --features whatsapp-web"
                    );
                    eprintln!(
                        "  ⚠ WhatsApp Web is configured but the 'whatsapp-web' feature is not compiled in."
                    );
                    eprintln!("    Rebuild with: cargo build --features whatsapp-web");
                }
            }
            _ => {
                tracing::warn!(
                    "WhatsApp config invalid: neither phone_number_id (Cloud API) nor session_path (Web) is set"
                );
            }
        }
    }

    if let Some(ref lq) = config.channels_config.linq {
        channels.push(ConfiguredChannel {
            display_name: "Linq",
            channel: Arc::new(LinqChannel::new(
                lq.api_token.clone(),
                lq.from_phone.clone(),
                lq.allowed_senders.clone(),
            )),
        });
    }

    if let Some(ref wati_cfg) = config.channels_config.wati {
        channels.push(ConfiguredChannel {
            display_name: "WATI",
            channel: Arc::new(WatiChannel::new_with_proxy(
                wati_cfg.api_token.clone(),
                wati_cfg.api_url.clone(),
                wati_cfg.tenant_id.clone(),
                wati_cfg.allowed_numbers.clone(),
                wati_cfg.proxy_url.clone(),
            )),
        });
    }

    if let Some(ref nc) = config.channels_config.nextcloud_talk {
        channels.push(ConfiguredChannel {
            display_name: "Nextcloud Talk",
            channel: Arc::new(NextcloudTalkChannel::new_with_proxy(
                nc.base_url.clone(),
                nc.app_token.clone(),
                nc.allowed_users.clone(),
                nc.proxy_url.clone(),
            )),
        });
    }

    if let Some(ref email_cfg) = config.channels_config.email {
        channels.push(ConfiguredChannel {
            display_name: "Email",
            channel: Arc::new(EmailChannel::new(email_cfg.clone())),
        });
    }

    if let Some(ref irc) = config.channels_config.irc {
        channels.push(ConfiguredChannel {
            display_name: "IRC",
            channel: Arc::new(IrcChannel::new(irc::IrcChannelConfig {
                server: irc.server.clone(),
                port: irc.port,
                nickname: irc.nickname.clone(),
                username: irc.username.clone(),
                channels: irc.channels.clone(),
                allowed_users: irc.allowed_users.clone(),
                server_password: irc.server_password.clone(),
                nickserv_password: irc.nickserv_password.clone(),
                sasl_password: irc.sasl_password.clone(),
                verify_tls: irc.verify_tls.unwrap_or(true),
            })),
        });
    }

    #[cfg(feature = "channel-lark")]
    if let Some(ref lk) = config.channels_config.lark {
        if lk.use_feishu {
            if config.channels_config.feishu.is_some() {
                tracing::warn!(
                    "Both [channels_config.feishu] and legacy [channels_config.lark].use_feishu=true are configured; ignoring legacy Feishu fallback in lark."
                );
            } else {
                tracing::warn!(
                    "Using legacy [channels_config.lark].use_feishu=true compatibility path; prefer [channels_config.feishu]."
                );
                channels.push(ConfiguredChannel {
                    display_name: "Feishu",
                    channel: Arc::new(LarkChannel::from_config(lk)),
                });
            }
        } else {
            channels.push(ConfiguredChannel {
                display_name: "Lark",
                channel: Arc::new(LarkChannel::from_lark_config(lk)),
            });
        }
    }

    #[cfg(feature = "channel-lark")]
    if let Some(ref fs) = config.channels_config.feishu {
        channels.push(ConfiguredChannel {
            display_name: "Feishu",
            channel: Arc::new(LarkChannel::from_feishu_config(fs)),
        });
    }

    #[cfg(not(feature = "channel-lark"))]
    if config.channels_config.lark.is_some() || config.channels_config.feishu.is_some() {
        tracing::warn!(
            "Lark/Feishu channel is configured but this build was compiled without `channel-lark`; skipping Lark/Feishu health check."
        );
    }

    if let Some(ref dt) = config.channels_config.dingtalk {
        channels.push(ConfiguredChannel {
            display_name: "DingTalk",
            channel: Arc::new(
                DingTalkChannel::new(
                    dt.client_id.clone(),
                    dt.client_secret.clone(),
                    dt.allowed_users.clone(),
                )
                .with_proxy_url(dt.proxy_url.clone()),
            ),
        });
    }

    if let Some(ref qq) = config.channels_config.qq {
        channels.push(ConfiguredChannel {
            display_name: "QQ",
            channel: Arc::new(
                QQChannel::new(
                    qq.app_id.clone(),
                    qq.app_secret.clone(),
                    qq.allowed_users.clone(),
                )
                .with_workspace_dir(config.workspace_dir.clone())
                .with_proxy_url(qq.proxy_url.clone()),
            ),
        });
    }

    if let Some(ref tw) = config.channels_config.twitter {
        channels.push(ConfiguredChannel {
            display_name: "X/Twitter",
            channel: Arc::new(TwitterChannel::new(
                tw.bearer_token.clone(),
                tw.allowed_users.clone(),
            )),
        });
    }

    if let Some(ref mc) = config.channels_config.mochat {
        channels.push(ConfiguredChannel {
            display_name: "Mochat",
            channel: Arc::new(MochatChannel::new(
                mc.api_url.clone(),
                mc.api_token.clone(),
                mc.allowed_users.clone(),
                mc.poll_interval_secs,
            )),
        });
    }

    if let Some(ref wc) = config.channels_config.wecom {
        channels.push(ConfiguredChannel {
            display_name: "WeCom",
            channel: Arc::new(WeComChannel::new(
                wc.webhook_key.clone(),
                wc.allowed_users.clone(),
            )),
        });
    }

    if let Some(ref ct) = config.channels_config.clawdtalk {
        channels.push(ConfiguredChannel {
            display_name: "ClawdTalk",
            channel: Arc::new(ClawdTalkChannel::new(ct.clone())),
        });
    }

    // Notion database poller channel
    if config.notion.enabled && !config.notion.database_id.trim().is_empty() {
        let notion_api_key = if config.notion.api_key.trim().is_empty() {
            std::env::var("NOTION_API_KEY").unwrap_or_default()
        } else {
            config.notion.api_key.trim().to_string()
        };
        if notion_api_key.trim().is_empty() {
            tracing::warn!(
                "Notion channel enabled but no API key found (set notion.api_key or NOTION_API_KEY env var)"
            );
        } else {
            channels.push(ConfiguredChannel {
                display_name: "Notion",
                channel: Arc::new(NotionChannel::new(
                    notion_api_key,
                    config.notion.database_id.clone(),
                    config.notion.poll_interval_secs,
                    config.notion.status_property.clone(),
                    config.notion.input_property.clone(),
                    config.notion.result_property.clone(),
                    config.notion.max_concurrent,
                    config.notion.recover_stale,
                )),
            });
        }
    }

    if let Some(ref rd) = config.channels_config.reddit {
        channels.push(ConfiguredChannel {
            display_name: "Reddit",
            channel: Arc::new(RedditChannel::new(
                rd.client_id.clone(),
                rd.client_secret.clone(),
                rd.refresh_token.clone(),
                rd.username.clone(),
                rd.subreddit.clone(),
            )),
        });
    }

    if let Some(ref bs) = config.channels_config.bluesky {
        channels.push(ConfiguredChannel {
            display_name: "Bluesky",
            channel: Arc::new(BlueskyChannel::new(
                bs.handle.clone(),
                bs.app_password.clone(),
            )),
        });
    }

    if let Some(ref wh) = config.channels_config.webhook {
        channels.push(ConfiguredChannel {
            display_name: "Webhook",
            channel: Arc::new(WebhookChannel::new(
                wh.port,
                wh.listen_path.clone(),
                wh.send_url.clone(),
                wh.send_method.clone(),
                wh.auth_header.clone(),
                wh.secret.clone(),
            )),
        });
    }

    channels
}

/// Run health checks for configured channels.
pub async fn doctor_channels(config: Config) -> Result<()> {
    #[allow(unused_mut)]
    let mut channels = collect_configured_channels(&config, "health check");

    #[cfg(feature = "channel-nostr")]
    if let Some(ref ns) = config.channels_config.nostr {
        channels.push(ConfiguredChannel {
            display_name: "Nostr",
            channel: Arc::new(
                NostrChannel::new(&ns.private_key, ns.relays.clone(), &ns.allowed_pubkeys).await?,
            ),
        });
    }

    if channels.is_empty() {
        println!("No real-time channels configured. Run `R.A.I.N. onboard` first.");
        return Ok(());
    }

    println!("🩺 R.A.I.N. Channel Doctor");
    println!();

    let mut healthy = 0_u32;
    let mut unhealthy = 0_u32;
    let mut timeout = 0_u32;

    for configured in channels {
        let result =
            tokio::time::timeout(Duration::from_secs(10), configured.channel.health_check()).await;
        let state = classify_health_result(&result);

        match state {
            ChannelHealthState::Healthy => {
                healthy += 1;
                println!("  ✅ {:<9} healthy", configured.display_name);
            }
            ChannelHealthState::Unhealthy => {
                unhealthy += 1;
                println!(
                    "  ❌ {:<9} unhealthy (auth/config/network)",
                    configured.display_name
                );
            }
            ChannelHealthState::Timeout => {
                timeout += 1;
                println!("  ⏱️  {:<9} timed out (>10s)", configured.display_name);
            }
        }
    }

    if config.channels_config.webhook.is_some() {
        println!("  ℹ️  Webhook   check via `R.A.I.N. gateway` then GET /health");
    }

    println!();
    println!("Summary: {healthy} healthy, {unhealthy} unhealthy, {timeout} timed out");
    Ok(())
}

/// Start all configured channels and route messages to the agent
#[allow(clippy::too_many_lines)]
pub async fn start_channels(config: Config) -> Result<()> {
    let provider_name = resolved_default_provider(&config);
    let provider_runtime_options = providers::ProviderRuntimeOptions {
        auth_profile_override: None,
        provider_api_url: config.api_url.clone(),
        rain_dir: config.config_path.parent().map(std::path::PathBuf::from),
        secrets_encrypt: config.secrets.encrypt,
        reasoning_enabled: config.runtime.reasoning_enabled,
        reasoning_effort: config.runtime.reasoning_effort.clone(),
        provider_timeout_secs: Some(config.provider_timeout_secs),
        extra_headers: config.extra_headers.clone(),
        api_path: config.api_path.clone(),
    };
    let provider: Arc<dyn Provider> = Arc::from(
        provider::create_resilient_provider_nonblocking(
            &provider_name,
            config.api_key.clone(),
            config.api_url.clone(),
            config.reliability.clone(),
            provider_runtime_options.clone(),
        )
        .await?,
    );

    // Warm up the provider connection pool (TLS handshake, DNS, HTTP/2 setup)
    // so the first real message doesn't hit a cold-start timeout.
    if let Err(e) = provider.warmup().await {
        tracing::warn!("Provider warmup failed (non-fatal): {e}");
    }

    let initial_stamp = config_file_stamp(&config.config_path).await;
    {
        let mut store = runtime_config_store()
            .lock()
            .unwrap_or_else(|e| e.into_inner());
        store.insert(
            config.config_path.clone(),
            RuntimeConfigState {
                defaults: runtime_defaults_from_config(&config),
                last_applied_stamp: initial_stamp,
            },
        );
    }

    let observer: Arc<dyn Observer> =
        Arc::from(observability::create_observer(&config.observability));
    let runtime: Arc<dyn runtime::RuntimeAdapter> =
        Arc::from(runtime::create_runtime(&config.runtime)?);
    let security = Arc::new(SecurityPolicy::from_config(
        &config.autonomy,
        &config.workspace_dir,
    ));
    let model = resolved_default_model(&config);
    let temperature = config.default_temperature;
    let mem: Arc<dyn Memory> = Arc::from(memory::create_memory_with_storage_and_routes(
        &config.memory,
        &config.embedding_routes,
        Some(&config.storage.provider.config),
        &config.workspace_dir,
        config.api_key.as_deref(),
    )?);
    let (composio_key, composio_entity_id) = if config.composio.enabled {
        (
            config.composio.api_key.as_deref(),
            Some(config.composio.entity_id.as_str()),
        )
    } else {
        (None, None)
    };
    // Build system prompt from workspace identity files + skills
    let workspace = config.workspace_dir.clone();
    let model_switch_state = ModelSwitchState::default();
    let (mut built_tools, delegate_handle_ch): (Vec<Box<dyn Tool>>, _) =
        tools::all_tools_with_runtime(
            Arc::new(config.clone()),
            &security,
            runtime,
            Arc::clone(&mem),
            composio_key,
            composio_entity_id,
            &config.browser,
            &config.http_request,
            &config.web_fetch,
            &workspace,
            &config.agents,
            config.api_key.as_deref(),
            &config,
            model_switch_state.clone(),
        );

    // Wire MCP tools into the registry before freezing — non-fatal.
    // When `deferred_loading` is enabled, MCP tools are NOT added eagerly.
    // Instead, a `tool_search` built-in is registered for on-demand loading.
    let mut deferred_section = String::new();
    let mut ch_activated_handle: Option<
        std::sync::Arc<std::sync::Mutex<crate::tools::ActivatedToolSet>>,
    > = None;
    if config.mcp.enabled && !config.mcp.servers.is_empty() {
        tracing::info!(
            "Initializing MCP client — {} server(s) configured",
            config.mcp.servers.len()
        );
        match crate::tools::McpRegistry::connect_all(&config.mcp.servers).await {
            Ok(registry) => {
                let registry = std::sync::Arc::new(registry);
                if config.mcp.deferred_loading {
                    let deferred_set = crate::tools::DeferredMcpToolSet::from_registry(
                        std::sync::Arc::clone(&registry),
                    )
                    .await;
                    tracing::info!(
                        "MCP deferred: {} tool stub(s) from {} server(s)",
                        deferred_set.len(),
                        registry.server_count()
                    );
                    deferred_section =
                        crate::tools::mcp_deferred::build_deferred_tools_section(&deferred_set);
                    let activated = std::sync::Arc::new(std::sync::Mutex::new(
                        crate::tools::ActivatedToolSet::new(),
                    ));
                    ch_activated_handle = Some(std::sync::Arc::clone(&activated));
                    built_tools.push(Box::new(crate::tools::ToolSearchTool::new(
                        deferred_set,
                        activated,
                    )));
                } else {
                    let names = registry.tool_names();
                    let mut registered = 0usize;
                    for name in names {
                        if let Some(def) = registry.get_tool_def(&name).await {
                            let wrapper: std::sync::Arc<dyn Tool> =
                                std::sync::Arc::new(crate::tools::McpToolWrapper::new(
                                    name,
                                    def,
                                    std::sync::Arc::clone(&registry),
                                ));
                            if let Some(ref handle) = delegate_handle_ch {
                                handle.write().push(std::sync::Arc::clone(&wrapper));
                            }
                            built_tools.push(Box::new(crate::tools::ArcToolRef(wrapper)));
                            registered += 1;
                        }
                    }
                    tracing::info!(
                        "MCP: {} tool(s) registered from {} server(s)",
                        registered,
                        registry.server_count()
                    );
                }
            }
            Err(e) => {
                // Non-fatal — daemon continues with the tools registered above.
                tracing::error!("MCP registry failed to initialize: {e:#}");
            }
        }
    }

    let shared_tools = built_tools
        .into_iter()
        .map(Arc::<dyn Tool>::from)
        .collect::<Vec<_>>();
    let tools_registry = Arc::new(
        shared_tools
            .iter()
            .map(|tool| Box::new(crate::tools::ArcToolRef(Arc::clone(tool))) as Box<dyn Tool>)
            .collect::<Vec<_>>(),
    );
    let manifest = load_runtime_agent_manifest(&workspace)?;
    let toolbox_template = build_runtime_toolbox_template(&shared_tools, manifest.as_ref());

    let skills = crate::skills::load_skills_with_config(&workspace, &config);

    // ── Load locale-aware tool descriptions ────────────────────────
    let i18n_locale = config
        .locale
        .as_deref()
        .filter(|s| !s.is_empty())
        .map(ToString::to_string)
        .unwrap_or_else(crate::i18n::detect_locale);
    let i18n_search_dirs = crate::i18n::default_search_dirs(&workspace);
    let i18n_descs = crate::i18n::ToolDescriptions::load(&i18n_locale, &i18n_search_dirs);

    // Collect tool descriptions for the prompt
    let mut tool_descs: Vec<(&str, &str)> = vec![
        (
            "shell",
            "Execute terminal commands. Use when: running local checks, build/test commands, diagnostics. Don't use when: a safer dedicated tool exists, or command is destructive without approval.",
        ),
        (
            "file_read",
            "Read file contents. Use when: inspecting project files, configs, logs. Don't use when: a targeted search is enough.",
        ),
        (
            "file_write",
            "Write file contents. Use when: applying focused edits, scaffolding files, updating docs/code. Don't use when: side effects are unclear or file ownership is uncertain.",
        ),
        (
            "memory_store",
            "Save to memory. Use when: preserving durable preferences, decisions, key context. Don't use when: information is transient/noisy/sensitive without need.",
        ),
        (
            "memory_recall",
            "Search memory. Use when: retrieving prior decisions, user preferences, historical context. Don't use when: answer is already in current context.",
        ),
        (
            "memory_forget",
            "Delete a memory entry. Use when: memory is incorrect/stale or explicitly requested for removal. Don't use when: impact is uncertain.",
        ),
    ];

    if matches!(
        config.skills.prompt_injection_mode,
        crate::config::SkillsPromptInjectionMode::Compact
    ) {
        tool_descs.push((
            "read_skill",
            "Load the full source for an available skill by name. Use when: compact mode only shows a summary and you need the complete skill instructions.",
        ));
    }

    if config.browser.enabled {
        tool_descs.push((
            "browser_open",
            "Open approved HTTPS URLs in system browser (allowlist-only, no scraping)",
        ));
    }
    if config.composio.enabled {
        tool_descs.push((
            "composio",
            "Execute actions on 1000+ apps via Composio (Gmail, Notion, GitHub, Slack, etc.). Use action='list' to discover actions, 'list_accounts' to retrieve connected account IDs, 'execute' to run (optionally with connected_account_id), and 'connect' for OAuth.",
        ));
    }
    tool_descs.push((
        "schedule",
        "Manage scheduled tasks (create/list/get/cancel/pause/resume). Supports recurring cron and one-shot delays.",
    ));
    tool_descs.push((
        "pushover",
        "Send a Pushover notification to your device. Requires PUSHOVER_TOKEN and PUSHOVER_USER_KEY in .env file.",
    ));
    if !config.agents.is_empty() {
        tool_descs.push((
            "delegate",
            "Delegate a subtask to a specialized agent. Use when: a task benefits from a different model (e.g. fast summarization, deep reasoning, code generation). The sub-agent runs a single prompt and returns its response.",
        ));
    }

    // Filter out tools excluded for non-CLI channels so the system prompt
    // does not advertise them for channel-driven runs.
    // Skip this filter when autonomy is `Full` — full-autonomy agents keep
    // all tools available regardless of channel.
    let excluded = &config.autonomy.non_cli_excluded_tools;
    if !excluded.is_empty() && config.autonomy.level != AutonomyLevel::Full {
        tool_descs.retain(|(name, _)| !excluded.iter().any(|ex| ex == name));
    }

    let bootstrap_max_chars = if config.agent.compact_context {
        Some(6000)
    } else {
        None
    };
    let tool_desc_catalog = Arc::new(
        tool_descs
            .iter()
            .map(|(name, desc)| ((*name).to_string(), (*desc).to_string()))
            .collect::<Vec<_>>(),
    );
    let bootstrap_toolbox = if config.autonomy.level == AutonomyLevel::Full {
        toolbox_template.fork_session()
    } else {
        toolbox_template.fork_session_with_exclusions(&config.autonomy.non_cli_excluded_tools)
    };
    let system_prompt = render_runtime_system_prompt(RuntimeSystemPromptContext {
        workspace_dir: &workspace,
        model_name: &model,
        tool_desc_catalog: tool_desc_catalog.as_ref(),
        skills: &skills,
        identity_config: Some(&config.identity),
        bootstrap_max_chars,
        autonomy_config: Some(&config.autonomy),
        native_tools: provider.supports_native_tools(),
        skills_prompt_mode: config.skills.prompt_injection_mode,
        tool_descriptions: Some(&i18n_descs),
        toolbox_manager: Some(&bootstrap_toolbox),
        tools_registry: tools_registry.as_ref(),
        activated_tools: ch_activated_handle.as_ref(),
        excluded_tools: if config.autonomy.level == AutonomyLevel::Full {
            &[]
        } else {
            &config.autonomy.non_cli_excluded_tools
        },
        deferred_section: &deferred_section,
    });

    if !skills.is_empty() {
        println!(
            "  🧩 Skills:   {}",
            skills
                .iter()
                .map(|s| s.name.as_str())
                .collect::<Vec<_>>()
                .join(", ")
        );
    }

    // Collect active channels from a shared builder to keep startup and doctor parity.
    #[allow(unused_mut)]
    let mut channels: Vec<Arc<dyn Channel>> =
        collect_configured_channels(&config, "runtime startup")
            .into_iter()
            .map(|configured| configured.channel)
            .collect();

    #[cfg(feature = "channel-nostr")]
    if let Some(ref ns) = config.channels_config.nostr {
        channels.push(Arc::new(
            NostrChannel::new(&ns.private_key, ns.relays.clone(), &ns.allowed_pubkeys).await?,
        ));
    }
    if channels.is_empty() {
        println!("No channels configured. Run `R.A.I.N. onboard` to set up channels.");
        return Ok(());
    }

    println!("🦀 R.A.I.N. Channel Server");
    println!("  🤖 Model:    {model}");
    let effective_backend = memory::effective_memory_backend_name(
        &config.memory.backend,
        Some(&config.storage.provider.config),
    );
    println!(
        "  🧠 Memory:   {} (auto-save: {})",
        effective_backend,
        if config.memory.auto_save { "on" } else { "off" }
    );
    println!(
        "  📡 Channels: {}",
        channels
            .iter()
            .map(|c| c.name())
            .collect::<Vec<_>>()
            .join(", ")
    );
    println!();
    println!("  Listening for messages... (Ctrl+C to stop)");
    println!();

    crate::health::mark_component_ok("channels");

    let initial_backoff_secs = config
        .reliability
        .channel_initial_backoff_secs
        .max(DEFAULT_CHANNEL_INITIAL_BACKOFF_SECS);
    let max_backoff_secs = config
        .reliability
        .channel_max_backoff_secs
        .max(DEFAULT_CHANNEL_MAX_BACKOFF_SECS);

    // Single message bus — all channels send messages here
    let (tx, rx) = tokio::sync::mpsc::channel::<traits::ChannelMessage>(100);

    // Spawn a listener for each channel
    let mut handles = Vec::new();
    for ch in &channels {
        handles.push(spawn_supervised_listener(
            ch.clone(),
            tx.clone(),
            initial_backoff_secs,
            max_backoff_secs,
        ));
    }
    drop(tx); // Drop our copy so rx closes when all channels stop

    let channels_by_name = Arc::new(
        channels
            .iter()
            .map(|ch| (ch.name().to_string(), Arc::clone(ch)))
            .collect::<HashMap<_, _>>(),
    );
    let max_in_flight_messages = compute_max_in_flight_messages(channels.len());

    println!("  🚦 In-flight message limit: {max_in_flight_messages}");

    let mut provider_cache_seed: HashMap<String, Arc<dyn Provider>> = HashMap::new();
    provider_cache_seed.insert(provider_name.clone(), Arc::clone(&provider));
    let message_timeout_secs =
        effective_channel_message_timeout_secs(config.channels_config.message_timeout_secs);
    let interrupt_on_new_message = config
        .channels_config
        .telegram
        .as_ref()
        .is_some_and(|tg| tg.interrupt_on_new_message);
    let interrupt_on_new_message_slack = config
        .channels_config
        .slack
        .as_ref()
        .is_some_and(|sl| sl.interrupt_on_new_message);
    let interrupt_on_new_message_discord = config
        .channels_config
        .discord
        .as_ref()
        .is_some_and(|dc| dc.interrupt_on_new_message);
    let interrupt_on_new_message_mattermost = config
        .channels_config
        .mattermost
        .as_ref()
        .is_some_and(|mm| mm.interrupt_on_new_message);
    let interrupt_on_new_message_matrix = config
        .channels_config
        .matrix
        .as_ref()
        .is_some_and(|mx| mx.interrupt_on_new_message);

    let runtime_ctx = Arc::new(ChannelRuntimeContext {
        channels_by_name,
        provider: Arc::clone(&provider),
        default_provider: Arc::new(provider_name),
        prompt_config: Arc::new(config.clone()),
        memory: Arc::clone(&mem),
        tools_registry: Arc::clone(&tools_registry),
        observer,
        system_prompt: Arc::new(system_prompt),
        dynamic_tools: DynamicToolRuntimeState {
            toolbox_template,
            tool_descs: Arc::clone(&tool_desc_catalog),
            tool_descriptions: Some(Arc::new(i18n_descs.clone())),
            deferred_section: Arc::new(deferred_section.clone()),
            bootstrap_max_chars,
        },
        model: Arc::new(model.clone()),
        temperature,
        auto_save_memory: config.memory.auto_save,
        max_tool_iterations: config.agent.max_tool_iterations,
        min_relevance_score: config.memory.min_relevance_score,
        conversation_histories: Arc::new(Mutex::new(HashMap::new())),
        pending_new_sessions: Arc::new(Mutex::new(HashSet::new())),
        provider_cache: Arc::new(parking_lot::Mutex::new(provider_cache_seed)),
        route_overrides: Arc::new(Mutex::new(HashMap::new())),
        api_key: config.api_key.clone(),
        api_url: config.api_url.clone(),
        reliability: Arc::new(config.reliability.clone()),
        provider_runtime_options,
        workspace_dir: Arc::new(config.workspace_dir.clone()),
        message_timeout_secs,
        interrupt_on_new_message: InterruptOnNewMessageConfig {
            telegram: interrupt_on_new_message,
            slack: interrupt_on_new_message_slack,
            discord: interrupt_on_new_message_discord,
            mattermost: interrupt_on_new_message_mattermost,
            matrix: interrupt_on_new_message_matrix,
        },
        multimodal: config.multimodal.clone(),
        hooks: if config.hooks.enabled {
            let mut runner = crate::hooks::HookRunner::new();
            if config.hooks.builtin.command_logger {
                runner.register(Box::new(crate::hooks::builtin::CommandLoggerHook::new()));
            }
            if config.hooks.builtin.webhook_audit.enabled {
                match crate::hooks::builtin::WebhookAuditHook::new(
                    config.hooks.builtin.webhook_audit.clone(),
                ) {
                    Ok(hook) => runner.register(Box::new(hook)),
                    Err(e) => {
                        tracing::error!(hook = "webhook-audit", error = %e, "failed to initialize webhook-audit hook; skipping");
                    }
                }
            }
            Some(Arc::new(runner))
        } else {
            None
        },
        non_cli_excluded_tools: Arc::new(config.autonomy.non_cli_excluded_tools.clone()),
        autonomy_level: config.autonomy.level,
        tool_call_dedup_exempt: Arc::new(config.agent.tool_call_dedup_exempt.clone()),
        model_routes: Arc::new(config.model_routes.clone()),
        query_classification: config.query_classification.clone(),
        ack_reactions: config.channels_config.ack_reactions,
        show_tool_calls: config.channels_config.show_tool_calls,
        session_store: if config.channels_config.session_persistence {
            match session_store::SessionStore::new(&config.workspace_dir) {
                Ok(store) => {
                    tracing::info!("📂 Session persistence enabled");
                    Some(Arc::new(store))
                }
                Err(e) => {
                    tracing::warn!("Session persistence disabled: {e}");
                    None
                }
            }
        } else {
            None
        },
        approval_manager: Arc::new(ApprovalManager::for_non_interactive(&config.autonomy)),
        activated_tools: ch_activated_handle,
        cost_tracking: crate::cost::CostTracker::get_or_init_global(
            config.cost.clone(),
            &config.workspace_dir,
        )
        .map(|tracker| ChannelCostTrackingState {
            tracker,
            prices: Arc::new(config.cost.prices.clone()),
        }),
        pacing: config.pacing.clone(),
        model_switch_state,
    });

    // Hydrate in-memory conversation histories from persisted JSONL session files.
    if let Some(ref store) = runtime_ctx.session_store {
        let mut hydrated = 0usize;
        let mut histories = runtime_ctx
            .conversation_histories
            .lock()
            .unwrap_or_else(|e| e.into_inner());
        for key in store.list_sessions() {
            let msgs = store.load(&key);
            if !msgs.is_empty() {
                hydrated += 1;
                histories.insert(key, msgs);
            }
        }
        drop(histories);
        if hydrated > 0 {
            tracing::info!("📂 Restored {hydrated} session(s) from disk");
        }
    }

    run_message_dispatch_loop(rx, runtime_ctx, max_in_flight_messages).await;

    // Wait for all channel tasks
    for h in handles {
        let _ = h.await;
    }

    Ok(())
}

#[cfg(test)]
mod tests;
