#[allow(clippy::wildcard_imports)]
use super::*;

/// Build a single channel instance by config section name (e.g. "telegram").
pub(super) struct ConfiguredChannel {
    pub(super) display_name: &'static str,
    pub(super) channel: Arc<dyn Channel>,
}

pub(super) fn collect_configured_channels(
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
                    tracing::warn!("WhatsApp Cloud API configured but missing required fields (phone_number_id, access_token, verify_token)");
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
                    tracing::warn!("WhatsApp Web backend requires 'whatsapp-web' feature. Enable with: cargo build --features whatsapp-web");
                    eprintln!("  ⚠ WhatsApp Web is configured but the 'whatsapp-web' feature is not compiled in.");
                    eprintln!("    Rebuild with: cargo build --features whatsapp-web");
                }
            }
            _ => {
                tracing::warn!("WhatsApp config invalid: neither phone_number_id (Cloud API) nor session_path (Web) is set");
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
        create_resilient_provider_nonblocking(
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

    let tools_registry = Arc::new(built_tools);

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
    let native_tools = provider.supports_native_tools();
    let mut system_prompt = build_system_prompt_with_mode_and_autonomy(
        &workspace,
        &model,
        &tool_descs,
        &skills,
        Some(&config.identity),
        bootstrap_max_chars,
        Some(&config.autonomy),
        native_tools,
        config.skills.prompt_injection_mode,
    );
    if !native_tools {
        system_prompt.push_str(&build_tool_instructions(
            tools_registry.as_ref(),
            Some(&i18n_descs),
        ));
    }

    // Append deferred MCP tool names so the LLM knows what is available
    if !deferred_section.is_empty() {
        system_prompt.push('\n');
        system_prompt.push_str(&deferred_section);
    }

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
        model: Arc::new(model.clone()),
        temperature,
        auto_save_memory: config.memory.auto_save,
        max_tool_iterations: config.agent.max_tool_iterations,
        min_relevance_score: config.memory.min_relevance_score,
        conversation_histories: Arc::new(Mutex::new(HashMap::new())),
        pending_new_sessions: Arc::new(Mutex::new(HashSet::new())),
        provider_cache: Arc::new(Mutex::new(provider_cache_seed)),
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
