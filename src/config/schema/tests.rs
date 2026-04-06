#[allow(clippy::wildcard_imports)]
use super::*;
use std::io;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;
use std::sync::{Arc, Mutex as StdMutex};
use tempfile::TempDir;
use tokio::sync::{Mutex, MutexGuard};
use tokio::test;
use tokio_stream::StreamExt;
use tokio_stream::wrappers::ReadDirStream;

// ── Tilde expansion ───────────────────────────────────────

#[test]
async fn expand_tilde_path_handles_absolute_path() {
    let path = expand_tilde_path("/absolute/path");
    assert_eq!(path, PathBuf::from("/absolute/path"));
}

#[test]
async fn expand_tilde_path_handles_relative_path() {
    let path = expand_tilde_path("relative/path");
    assert_eq!(path, PathBuf::from("relative/path"));
}

#[test]
async fn expand_tilde_path_expands_tilde_when_home_set() {
    // This test verifies that tilde expansion works when HOME is set.
    // In normal environments, HOME is set, so ~ should expand.
    let path = expand_tilde_path("~/.R.A.I.N.");
    // The path should not literally start with '~' if HOME is set
    // (it should be expanded to the actual home directory)
    if std::env::var("HOME").is_ok() {
        assert!(
            !path.to_string_lossy().starts_with('~'),
            "Tilde should be expanded when HOME is set"
        );
    }
}

// ── Defaults ─────────────────────────────────────────────

fn has_test_table(raw: &str, table: &str) -> bool {
    let exact = format!("[{table}]");
    let nested = format!("[{table}.");
    raw.lines()
        .map(str::trim)
        .any(|line| line == exact || line.starts_with(&nested))
}

fn parse_test_config(raw: &str) -> Config {
    let mut merged = raw.trim().to_string();
    for table in [
        "data_retention",
        "cloud_ops",
        "conversational_ai",
        "security",
        "security_ops",
    ] {
        if has_test_table(&merged, table) {
            continue;
        }
        if !merged.is_empty() {
            merged.push_str("\n\n");
        }
        merged.push('[');
        merged.push_str(table);
        merged.push(']');
    }
    merged.push('\n');
    toml::from_str(&merged).unwrap()
}

#[test]
async fn http_request_config_default_has_correct_values() {
    let cfg = HttpRequestConfig::default();
    assert_eq!(cfg.timeout_secs, 30);
    assert_eq!(cfg.max_response_size, 1_000_000);
    assert!(!cfg.enabled);
    assert!(cfg.allowed_domains.is_empty());
}

#[test]
async fn config_default_has_sane_values() {
    let c = Config::default();
    assert_eq!(c.default_provider.as_deref(), Some("openrouter"));
    assert!(c.default_model.as_deref().unwrap().contains("claude"));
    assert!((c.default_temperature - 0.7).abs() < f64::EPSILON);
    assert!(c.api_key.is_none());
    assert!(!c.skills.open_skills_enabled);
    assert!(!c.skills.allow_scripts);
    assert_eq!(
        c.skills.prompt_injection_mode,
        SkillsPromptInjectionMode::Full
    );
    assert_eq!(c.provider_timeout_secs, 120);
    assert!(c.workspace_dir.to_string_lossy().contains("workspace"));
    assert!(c.config_path.to_string_lossy().contains("config.toml"));
}

#[derive(Clone, Default)]
struct SharedLogBuffer(Arc<StdMutex<Vec<u8>>>);

struct SharedLogWriter(Arc<StdMutex<Vec<u8>>>);

impl SharedLogBuffer {
    fn captured(&self) -> String {
        String::from_utf8(self.0.lock().unwrap().clone()).unwrap()
    }
}

impl<'a> tracing_subscriber::fmt::MakeWriter<'a> for SharedLogBuffer {
    type Writer = SharedLogWriter;

    fn make_writer(&'a self) -> Self::Writer {
        SharedLogWriter(self.0.clone())
    }
}

impl io::Write for SharedLogWriter {
    fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
        self.0.lock().unwrap().extend_from_slice(buf);
        Ok(buf.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

#[test]
async fn config_dir_creation_error_mentions_openrc_and_path() {
    let msg = config_dir_creation_error(Path::new("/etc/R.A.I.N."));
    assert!(msg.contains("/etc/R.A.I.N."));
    assert!(msg.contains("OpenRC"));
    assert!(msg.contains("R.A.I.N."));
}

#[test]
async fn config_schema_export_contains_expected_contract_shape() {
    let schema = schemars::schema_for!(Config);
    let schema_json = serde_json::to_value(&schema).expect("schema should serialize to json");

    assert_eq!(
        schema_json
            .get("$schema")
            .and_then(serde_json::Value::as_str),
        Some("https://json-schema.org/draft/2020-12/schema")
    );

    let properties = schema_json
        .get("properties")
        .and_then(serde_json::Value::as_object)
        .expect("schema should expose top-level properties");

    assert!(properties.contains_key("default_provider"));
    assert!(properties.contains_key("skills"));
    assert!(properties.contains_key("gateway"));
    assert!(properties.contains_key("channels_config"));
    assert!(!properties.contains_key("workspace_dir"));
    assert!(!properties.contains_key("config_path"));

    assert!(
        schema_json
            .get("$defs")
            .and_then(serde_json::Value::as_object)
            .is_some(),
        "schema should include reusable type definitions"
    );
}

#[cfg(unix)]
#[test]
async fn save_sets_config_permissions_on_new_file() {
    let temp = TempDir::new().expect("temp dir");
    let config_path = temp.path().join("config.toml");
    let workspace_dir = temp.path().join("workspace");

    let mut config = Config::default();
    config.config_path = config_path.clone();
    config.workspace_dir = workspace_dir;

    config.save().await.expect("save config");

    let mode = std::fs::metadata(&config_path)
        .expect("config metadata")
        .permissions()
        .mode()
        & 0o777;
    assert_eq!(mode, 0o600);
}

#[test]
async fn observability_config_default() {
    let o = ObservabilityConfig::default();
    assert_eq!(o.backend, "none");
    assert_eq!(o.runtime_trace_mode, "none");
    assert_eq!(o.runtime_trace_path, "state/runtime-trace.jsonl");
    assert_eq!(o.runtime_trace_max_entries, 200);
}

#[test]
async fn autonomy_config_default() {
    let a = AutonomyConfig::default();
    assert_eq!(a.level, AutonomyLevel::Supervised);
    assert!(a.workspace_only);
    assert!(a.allowed_commands.contains(&"git".to_string()));
    assert!(a.allowed_commands.contains(&"cargo".to_string()));
    assert!(a.forbidden_paths.contains(&"/etc".to_string()));
    assert_eq!(a.max_actions_per_hour, 20);
    assert_eq!(a.max_cost_per_day_cents, 500);
    assert!(a.require_approval_for_medium_risk);
    assert!(a.block_high_risk_commands);
    assert!(a.shell_env_passthrough.is_empty());
}

#[test]
async fn runtime_config_default() {
    let r = RuntimeConfig::default();
    assert_eq!(r.kind, "native");
    assert_eq!(r.docker.image, "alpine:3.20");
    assert_eq!(r.docker.network, "none");
    assert_eq!(r.docker.memory_limit_mb, Some(512));
    assert_eq!(r.docker.cpu_limit, Some(1.0));
    assert!(r.docker.read_only_rootfs);
    assert!(r.docker.mount_workspace);
}

#[test]
async fn heartbeat_config_default() {
    let h = HeartbeatConfig::default();
    assert!(!h.enabled);
    assert_eq!(h.interval_minutes, 5);
    assert!(h.message.is_none());
    assert!(h.target.is_none());
    assert!(h.to.is_none());
}

#[test]
async fn heartbeat_config_parses_delivery_aliases() {
    let raw = r#"
enabled = true
interval_minutes = 10
message = "Ping"
channel = "telegram"
recipient = "42"
"#;
    let parsed: HeartbeatConfig = toml::from_str(raw).unwrap();
    assert!(parsed.enabled);
    assert_eq!(parsed.interval_minutes, 10);
    assert_eq!(parsed.message.as_deref(), Some("Ping"));
    assert_eq!(parsed.target.as_deref(), Some("telegram"));
    assert_eq!(parsed.to.as_deref(), Some("42"));
}

#[test]
async fn cron_config_default() {
    let c = CronConfig::default();
    assert!(c.enabled);
    assert_eq!(c.max_run_history, 50);
}

#[test]
async fn cron_config_serde_roundtrip() {
    let c = CronConfig {
        enabled: false,
        catch_up_on_startup: false,
        max_run_history: 100,
    };
    let json = serde_json::to_string(&c).unwrap();
    let parsed: CronConfig = serde_json::from_str(&json).unwrap();
    assert!(!parsed.enabled);
    assert!(!parsed.catch_up_on_startup);
    assert_eq!(parsed.max_run_history, 100);
}

#[test]
async fn config_defaults_cron_when_section_missing() {
    let toml_str = r#"
workspace_dir = "/tmp/workspace"
config_path = "/tmp/config.toml"
default_temperature = 0.7
"#;

    let parsed = parse_test_config(toml_str);
    assert!(parsed.cron.enabled);
    assert!(parsed.cron.catch_up_on_startup);
    assert_eq!(parsed.cron.max_run_history, 50);
}

#[test]
async fn memory_config_default_hygiene_settings() {
    let m = MemoryConfig::default();
    assert_eq!(m.backend, "sqlite");
    assert!(m.auto_save);
    assert!(m.hygiene_enabled);
    assert_eq!(m.archive_after_days, 7);
    assert_eq!(m.purge_after_days, 30);
    assert_eq!(m.conversation_retention_days, 30);
    assert!(m.sqlite_open_timeout_secs.is_none());
}

#[test]
async fn storage_provider_config_defaults() {
    let storage = StorageConfig::default();
    assert!(storage.provider.config.provider.is_empty());
    assert!(storage.provider.config.db_url.is_none());
    assert_eq!(storage.provider.config.schema, "public");
    assert_eq!(storage.provider.config.table, "memories");
    assert!(storage.provider.config.connect_timeout_secs.is_none());
}

#[test]
async fn channels_config_default() {
    let c = ChannelsConfig::default();
    assert!(c.cli);
    assert!(c.telegram.is_none());
    assert!(c.discord.is_none());
    assert!(!c.show_tool_calls);
}

#[test]
async fn channels_module_exports_config_types() {
    let c = super::channels::ChannelsConfig::default();
    let _ = std::mem::size_of::<super::channels::TelegramConfig>();
    assert!(c.cli);
}

#[test]
async fn proxy_module_exports_runtime_types() {
    let proxy = super::proxy::ProxyConfig::default();
    let _ = std::mem::size_of::<super::proxy::RuntimeProxyStateHandle>();
    assert_eq!(proxy.scope, super::proxy::ProxyScope::Rain);
}

#[test]
async fn security_module_exports_config_types() {
    let security = super::security::SecurityConfig::default();
    let _ = std::mem::size_of::<super::security::NotionConfig>();
    let _ = std::mem::size_of::<super::security::JiraConfig>();
    assert_eq!(security.otp.method, super::security::OtpMethod::Totp);
}

// ── Serde round-trip ─────────────────────────────────────

#[test]
async fn config_toml_roundtrip() {
    let config = Config {
        workspace_dir: PathBuf::from("/tmp/test/workspace"),
        config_path: PathBuf::from("/tmp/test/config.toml"),
        api_key: Some("sk-test-key".into()),
        api_url: None,
        api_path: None,
        default_provider: Some("openrouter".into()),
        default_model: Some("gpt-4o".into()),
        model_providers: HashMap::new(),
        default_temperature: 0.5,
        provider_timeout_secs: 120,
        extra_headers: HashMap::new(),
        observability: ObservabilityConfig {
            backend: "log".into(),
            ..ObservabilityConfig::default()
        },
        autonomy: AutonomyConfig {
            level: AutonomyLevel::Full,
            workspace_only: false,
            allowed_commands: vec!["docker".into()],
            forbidden_paths: vec!["/secret".into()],
            max_actions_per_hour: 50,
            max_cost_per_day_cents: 1000,
            require_approval_for_medium_risk: false,
            block_high_risk_commands: true,
            shell_env_passthrough: vec!["DATABASE_URL".into()],
            auto_approve: vec!["file_read".into()],
            always_ask: vec![],
            allowed_roots: vec![],
            non_cli_excluded_tools: vec![],
        },
        backup: BackupConfig::default(),
        data_retention: DataRetentionConfig::default(),
        cloud_ops: CloudOpsConfig::default(),
        conversational_ai: ConversationalAiConfig::default(),
        security: SecurityConfig::default(),
        security_ops: SecurityOpsConfig::default(),
        runtime: RuntimeConfig {
            kind: "docker".into(),
            ..RuntimeConfig::default()
        },
        reliability: ReliabilityConfig::default(),
        scheduler: SchedulerConfig::default(),
        skills: SkillsConfig::default(),
        model_routes: Vec::new(),
        embedding_routes: Vec::new(),
        query_classification: QueryClassificationConfig::default(),
        heartbeat: HeartbeatConfig {
            enabled: true,
            interval_minutes: 15,
            two_phase: true,
            message: Some("Check London time".into()),
            target: Some("telegram".into()),
            to: Some("123456".into()),
            ..HeartbeatConfig::default()
        },
        cron: CronConfig::default(),
        channels_config: ChannelsConfig {
            cli: true,
            telegram: Some(TelegramConfig {
                bot_token: "123:ABC".into(),
                allowed_users: vec!["user1".into()],
                stream_mode: StreamMode::default(),
                draft_update_interval_ms: default_draft_update_interval_ms(),
                interrupt_on_new_message: false,
                mention_only: false,
                ack_reactions: None,
                proxy_url: None,
            }),
            discord: None,
            slack: None,
            mattermost: None,
            webhook: None,
            imessage: None,
            matrix: None,
            signal: None,
            whatsapp: None,
            linq: None,
            wati: None,
            nextcloud_talk: None,
            email: None,
            irc: None,
            lark: None,
            feishu: None,
            dingtalk: None,
            wecom: None,
            qq: None,
            twitter: None,
            mochat: None,
            #[cfg(feature = "channel-nostr")]
            nostr: None,
            clawdtalk: None,
            reddit: None,
            bluesky: None,
            message_timeout_secs: 300,
            ack_reactions: true,
            show_tool_calls: true,
            session_persistence: true,
            session_backend: default_session_backend(),
            session_ttl_hours: 0,
        },
        memory: MemoryConfig::default(),
        storage: StorageConfig::default(),
        tunnel: TunnelConfig::default(),
        gateway: GatewayConfig::default(),
        composio: ComposioConfig::default(),
        microsoft365: Microsoft365Config::default(),
        secrets: SecretsConfig::default(),
        browser: BrowserConfig::default(),
        browser_delegate: crate::tools::browser_delegate::BrowserDelegateConfig::default(),
        http_request: HttpRequestConfig::default(),
        multimodal: MultimodalConfig::default(),
        web_fetch: WebFetchConfig::default(),
        text_browser: TextBrowserConfig::default(),
        web_search: WebSearchConfig::default(),
        project_intel: ProjectIntelConfig::default(),
        google_workspace: GoogleWorkspaceConfig::default(),
        proxy: ProxyConfig::default(),
        agent: AgentConfig::default(),
        pacing: PacingConfig::default(),
        identity: IdentityConfig::default(),
        cost: CostConfig::default(),
        peripherals: PeripheralsConfig::default(),
        delegate: DelegateToolConfig::default(),
        agents: HashMap::new(),
        swarms: HashMap::new(),
        hooks: HooksConfig::default(),
        hardware: HardwareConfig::default(),
        transcription: TranscriptionConfig::default(),
        tts: TtsConfig::default(),
        mcp: McpConfig::default(),
        nodes: NodesConfig::default(),
        workspace: WorkspaceConfig::default(),
        notion: NotionConfig::default(),
        jira: JiraConfig::default(),
        node_transport: NodeTransportConfig::default(),
        knowledge: KnowledgeConfig::default(),
        linkedin: LinkedInConfig::default(),
        plugins: PluginsConfig::default(),
        locale: None,
        verifiable_intent: VerifiableIntentConfig::default(),
        claude_code: ClaudeCodeConfig::default(),
        tribev2: TribeV2Config::default(),
    };

    let toml_str = toml::to_string_pretty(&config).unwrap();
    let parsed = parse_test_config(&toml_str);

    assert_eq!(parsed.api_key, config.api_key);
    assert_eq!(parsed.default_provider, config.default_provider);
    assert_eq!(parsed.default_model, config.default_model);
    assert!((parsed.default_temperature - config.default_temperature).abs() < f64::EPSILON);
    assert_eq!(parsed.observability.backend, "log");
    assert_eq!(parsed.observability.runtime_trace_mode, "none");
    assert_eq!(parsed.autonomy.level, AutonomyLevel::Full);
    assert!(!parsed.autonomy.workspace_only);
    assert_eq!(parsed.runtime.kind, "docker");
    assert!(parsed.heartbeat.enabled);
    assert_eq!(parsed.heartbeat.interval_minutes, 15);
    assert_eq!(
        parsed.heartbeat.message.as_deref(),
        Some("Check London time")
    );
    assert_eq!(parsed.heartbeat.target.as_deref(), Some("telegram"));
    assert_eq!(parsed.heartbeat.to.as_deref(), Some("123456"));
    assert!(parsed.channels_config.telegram.is_some());
    assert_eq!(
        parsed.channels_config.telegram.unwrap().bot_token,
        "123:ABC"
    );
}

#[test]
async fn config_minimal_toml_uses_defaults() {
    let minimal = r#"
workspace_dir = "/tmp/ws"
config_path = "/tmp/config.toml"
default_temperature = 0.7
"#;
    let parsed = parse_test_config(minimal);
    assert!(parsed.api_key.is_none());
    assert!(parsed.default_provider.is_none());
    assert_eq!(parsed.observability.backend, "none");
    assert_eq!(parsed.observability.runtime_trace_mode, "none");
    assert_eq!(parsed.autonomy.level, AutonomyLevel::Supervised);
    assert_eq!(parsed.runtime.kind, "native");
    assert!(!parsed.heartbeat.enabled);
    assert!(parsed.channels_config.cli);
    assert!(parsed.memory.hygiene_enabled);
    assert_eq!(parsed.memory.archive_after_days, 7);
    assert_eq!(parsed.memory.purge_after_days, 30);
    assert_eq!(parsed.memory.conversation_retention_days, 30);
    // provider_timeout_secs defaults to 120 when not specified
    assert_eq!(parsed.provider_timeout_secs, 120);
}

#[test]
async fn provider_timeout_secs_parses_from_toml() {
    let raw = r#"
default_temperature = 0.7
provider_timeout_secs = 300
"#;
    let parsed = parse_test_config(raw);
    assert_eq!(parsed.provider_timeout_secs, 300);
}

#[test]
async fn parse_extra_headers_env_basic() {
    let headers = parse_extra_headers_env("User-Agent:MyApp/1.0,X-Title:R.A.I.N.");
    assert_eq!(headers.len(), 2);
    assert_eq!(
        headers[0],
        ("User-Agent".to_string(), "MyApp/1.0".to_string())
    );
    assert_eq!(headers[1], ("X-Title".to_string(), "R.A.I.N.".to_string()));
}

#[test]
async fn parse_extra_headers_env_with_url_value() {
    let headers = parse_extra_headers_env("HTTP-Referer:https://github.com/R.A.I.N.-labs/R.A.I.N.");
    assert_eq!(headers.len(), 1);
    // Only splits on first colon, preserving URL colons in value
    assert_eq!(headers[0].0, "HTTP-Referer");
    assert_eq!(headers[0].1, "https://github.com/R.A.I.N.-labs/R.A.I.N.");
}

#[test]
async fn parse_extra_headers_env_empty_string() {
    let headers = parse_extra_headers_env("");
    assert!(headers.is_empty());
}

#[test]
async fn parse_extra_headers_env_whitespace_trimming() {
    let headers = parse_extra_headers_env("  X-Title : R.A.I.N. , User-Agent : cli/1.0 ");
    assert_eq!(headers.len(), 2);
    assert_eq!(headers[0], ("X-Title".to_string(), "R.A.I.N.".to_string()));
    assert_eq!(
        headers[1],
        ("User-Agent".to_string(), "cli/1.0".to_string())
    );
}

#[test]
async fn parse_extra_headers_env_skips_malformed() {
    let headers = parse_extra_headers_env("X-Valid:value,no-colon-here,Another:ok");
    assert_eq!(headers.len(), 2);
    assert_eq!(headers[0], ("X-Valid".to_string(), "value".to_string()));
    assert_eq!(headers[1], ("Another".to_string(), "ok".to_string()));
}

#[test]
async fn parse_extra_headers_env_skips_empty_key() {
    let headers = parse_extra_headers_env(":value,X-Valid:ok");
    assert_eq!(headers.len(), 1);
    assert_eq!(headers[0], ("X-Valid".to_string(), "ok".to_string()));
}

#[test]
async fn parse_extra_headers_env_allows_empty_value() {
    let headers = parse_extra_headers_env("X-Empty:");
    assert_eq!(headers.len(), 1);
    assert_eq!(headers[0], ("X-Empty".to_string(), String::new()));
}

#[test]
async fn parse_extra_headers_env_trailing_comma() {
    let headers = parse_extra_headers_env("X-Title:R.A.I.N.,");
    assert_eq!(headers.len(), 1);
    assert_eq!(headers[0], ("X-Title".to_string(), "R.A.I.N.".to_string()));
}

#[test]
async fn extra_headers_parses_from_toml() {
    let raw = r#"
default_temperature = 0.7

[extra_headers]
User-Agent = "MyApp/1.0"
X-Title = "R.A.I.N."
"#;
    let parsed = parse_test_config(raw);
    assert_eq!(parsed.extra_headers.len(), 2);
    assert_eq!(parsed.extra_headers.get("User-Agent").unwrap(), "MyApp/1.0");
    assert_eq!(parsed.extra_headers.get("X-Title").unwrap(), "R.A.I.N.");
}

#[test]
async fn extra_headers_defaults_to_empty() {
    let raw = r#"
default_temperature = 0.7
"#;
    let parsed = parse_test_config(raw);
    assert!(parsed.extra_headers.is_empty());
}

#[test]
async fn storage_provider_dburl_alias_deserializes() {
    let raw = r#"
default_temperature = 0.7

[storage.provider.config]
provider = "postgres"
dbURL = "postgres://postgres:postgres@localhost:5432/R.A.I.N."
schema = "public"
table = "memories"
connect_timeout_secs = 12
"#;

    let parsed = parse_test_config(raw);
    assert_eq!(parsed.storage.provider.config.provider, "postgres");
    assert_eq!(
        parsed.storage.provider.config.db_url.as_deref(),
        Some("postgres://postgres:postgres@localhost:5432/R.A.I.N.")
    );
    assert_eq!(parsed.storage.provider.config.schema, "public");
    assert_eq!(parsed.storage.provider.config.table, "memories");
    assert_eq!(
        parsed.storage.provider.config.connect_timeout_secs,
        Some(12)
    );
}

#[test]
async fn runtime_reasoning_enabled_deserializes() {
    let raw = r#"
default_temperature = 0.7

[runtime]
reasoning_enabled = false
"#;

    let parsed = parse_test_config(raw);
    assert_eq!(parsed.runtime.reasoning_enabled, Some(false));
}

#[test]
async fn runtime_reasoning_effort_deserializes() {
    let raw = r#"
default_temperature = 0.7

[runtime]
reasoning_effort = "HIGH"
"#;

    let parsed: Config = toml::from_str(raw).unwrap();
    assert_eq!(parsed.runtime.reasoning_effort.as_deref(), Some("high"));
}

#[test]
async fn runtime_reasoning_effort_rejects_invalid_values() {
    let raw = r#"
default_temperature = 0.7

[runtime]
reasoning_effort = "turbo"
"#;

    let error = toml::from_str::<Config>(raw).expect_err("invalid value should fail");
    assert!(error.to_string().contains("reasoning_effort"));
}

#[test]
async fn agent_config_defaults() {
    let cfg = AgentConfig::default();
    assert!(cfg.compact_context);
    assert_eq!(cfg.max_tool_iterations, 10);
    assert_eq!(cfg.max_history_messages, 50);
    assert!(!cfg.parallel_tools);
    assert_eq!(cfg.tool_dispatcher, "auto");
}

#[test]
async fn agent_config_deserializes() {
    let raw = r#"
default_temperature = 0.7
[agent]
compact_context = true
max_tool_iterations = 20
max_history_messages = 80
parallel_tools = true
tool_dispatcher = "xml"
"#;
    let parsed = parse_test_config(raw);
    assert!(parsed.agent.compact_context);
    assert_eq!(parsed.agent.max_tool_iterations, 20);
    assert_eq!(parsed.agent.max_history_messages, 80);
    assert!(parsed.agent.parallel_tools);
    assert_eq!(parsed.agent.tool_dispatcher, "xml");
}

#[test]
async fn pacing_config_defaults_are_all_none_or_empty() {
    let cfg = PacingConfig::default();
    assert!(cfg.step_timeout_secs.is_none());
    assert!(cfg.loop_detection_min_elapsed_secs.is_none());
    assert!(cfg.loop_ignore_tools.is_empty());
    assert!(cfg.message_timeout_scale_max.is_none());
}

#[test]
async fn pacing_config_deserializes_from_toml() {
    let raw = r#"
default_temperature = 0.7
[pacing]
step_timeout_secs = 120
loop_detection_min_elapsed_secs = 60
loop_ignore_tools = ["browser_screenshot", "browser_navigate"]
message_timeout_scale_max = 8
"#;
    let parsed: Config = toml::from_str(raw).unwrap();
    assert_eq!(parsed.pacing.step_timeout_secs, Some(120));
    assert_eq!(parsed.pacing.loop_detection_min_elapsed_secs, Some(60));
    assert_eq!(
        parsed.pacing.loop_ignore_tools,
        vec!["browser_screenshot", "browser_navigate"]
    );
    assert_eq!(parsed.pacing.message_timeout_scale_max, Some(8));
}

#[test]
async fn pacing_config_absent_preserves_defaults() {
    let raw = r#"
default_temperature = 0.7
"#;
    let parsed: Config = toml::from_str(raw).unwrap();
    assert!(parsed.pacing.step_timeout_secs.is_none());
    assert!(parsed.pacing.loop_detection_min_elapsed_secs.is_none());
    assert!(parsed.pacing.loop_ignore_tools.is_empty());
    assert!(parsed.pacing.message_timeout_scale_max.is_none());
}

#[tokio::test]
async fn sync_directory_handles_existing_directory() {
    let dir =
        std::env::temp_dir().join(format!("rain_test_sync_directory_{}", uuid::Uuid::new_v4()));
    fs::create_dir_all(&dir).await.unwrap();

    sync_directory(&dir).await.unwrap();

    let _ = fs::remove_dir_all(&dir).await;
}

#[tokio::test]
async fn config_save_and_load_tmpdir() {
    let dir = std::env::temp_dir().join("rain_test_config");
    let _ = fs::remove_dir_all(&dir).await;
    fs::create_dir_all(&dir).await.unwrap();

    let config_path = dir.join("config.toml");
    let config = Config {
        workspace_dir: dir.join("workspace"),
        config_path: config_path.clone(),
        api_key: Some("sk-roundtrip".into()),
        api_url: None,
        api_path: None,
        default_provider: Some("openrouter".into()),
        default_model: Some("test-model".into()),
        model_providers: HashMap::new(),
        default_temperature: 0.9,
        provider_timeout_secs: 120,
        extra_headers: HashMap::new(),
        observability: ObservabilityConfig::default(),
        autonomy: AutonomyConfig::default(),
        backup: BackupConfig::default(),
        data_retention: DataRetentionConfig::default(),
        cloud_ops: CloudOpsConfig::default(),
        conversational_ai: ConversationalAiConfig::default(),
        security: SecurityConfig::default(),
        security_ops: SecurityOpsConfig::default(),
        runtime: RuntimeConfig::default(),
        reliability: ReliabilityConfig::default(),
        scheduler: SchedulerConfig::default(),
        skills: SkillsConfig::default(),
        model_routes: Vec::new(),
        embedding_routes: Vec::new(),
        query_classification: QueryClassificationConfig::default(),
        heartbeat: HeartbeatConfig::default(),
        cron: CronConfig::default(),
        channels_config: ChannelsConfig::default(),
        memory: MemoryConfig::default(),
        storage: StorageConfig::default(),
        tunnel: TunnelConfig::default(),
        gateway: GatewayConfig::default(),
        composio: ComposioConfig::default(),
        microsoft365: Microsoft365Config::default(),
        secrets: SecretsConfig::default(),
        browser: BrowserConfig::default(),
        browser_delegate: crate::tools::browser_delegate::BrowserDelegateConfig::default(),
        http_request: HttpRequestConfig::default(),
        multimodal: MultimodalConfig::default(),
        web_fetch: WebFetchConfig::default(),
        text_browser: TextBrowserConfig::default(),
        web_search: WebSearchConfig::default(),
        project_intel: ProjectIntelConfig::default(),
        google_workspace: GoogleWorkspaceConfig::default(),
        proxy: ProxyConfig::default(),
        agent: AgentConfig::default(),
        pacing: PacingConfig::default(),
        identity: IdentityConfig::default(),
        cost: CostConfig::default(),
        peripherals: PeripheralsConfig::default(),
        delegate: DelegateToolConfig::default(),
        agents: HashMap::new(),
        swarms: HashMap::new(),
        hooks: HooksConfig::default(),
        hardware: HardwareConfig::default(),
        transcription: TranscriptionConfig::default(),
        tts: TtsConfig::default(),
        mcp: McpConfig::default(),
        nodes: NodesConfig::default(),
        workspace: WorkspaceConfig::default(),
        notion: NotionConfig::default(),
        jira: JiraConfig::default(),
        node_transport: NodeTransportConfig::default(),
        knowledge: KnowledgeConfig::default(),
        linkedin: LinkedInConfig::default(),
        plugins: PluginsConfig::default(),
        locale: None,
        verifiable_intent: VerifiableIntentConfig::default(),
        claude_code: ClaudeCodeConfig::default(),
        tribev2: TribeV2Config::default(),
    };

    config.save().await.unwrap();
    assert!(config_path.exists());

    let contents = tokio::fs::read_to_string(&config_path).await.unwrap();
    let loaded: Config = toml::from_str(&contents).unwrap();
    assert!(
        loaded
            .api_key
            .as_deref()
            .is_some_and(crate::security::SecretStore::is_encrypted)
    );
    let store = crate::security::SecretStore::new(&dir, true);
    let decrypted = store.decrypt(loaded.api_key.as_deref().unwrap()).unwrap();
    assert_eq!(decrypted, "sk-roundtrip");
    assert_eq!(loaded.default_model.as_deref(), Some("test-model"));
    assert!((loaded.default_temperature - 0.9).abs() < f64::EPSILON);

    let _ = fs::remove_dir_all(&dir).await;
}

#[tokio::test]
async fn config_save_encrypts_nested_credentials() {
    let dir = std::env::temp_dir().join(format!(
        "rain_test_nested_credentials_{}",
        uuid::Uuid::new_v4()
    ));
    fs::create_dir_all(&dir).await.unwrap();

    let mut config = Config::default();
    config.workspace_dir = dir.join("workspace");
    config.config_path = dir.join("config.toml");
    config.api_key = Some("root-credential".into());
    config.composio.api_key = Some("composio-credential".into());
    config.browser.computer_use.api_key = Some("browser-credential".into());
    config.web_search.brave_api_key = Some("brave-credential".into());
    config.storage.provider.config.db_url = Some("postgres://user:pw@host/db".into());
    config.channels_config.feishu = Some(FeishuConfig {
        app_id: "cli_feishu_123".into(),
        app_secret: "feishu-secret".into(),
        encrypt_key: Some("feishu-encrypt".into()),
        verification_token: Some("feishu-verify".into()),
        allowed_users: vec!["*".into()],
        receive_mode: LarkReceiveMode::Websocket,
        port: None,
        proxy_url: None,
    });

    config.agents.insert(
        "worker".into(),
        DelegateAgentConfig {
            provider: "openrouter".into(),
            model: "model-test".into(),
            system_prompt: None,
            api_key: Some("agent-credential".into()),
            temperature: None,
            max_depth: 3,
            agentic: false,
            allowed_tools: Vec::new(),
            manifest_path: None,
            max_iterations: 10,
            timeout_secs: None,
            agentic_timeout_secs: None,
            skills_directory: None,
        },
    );

    config.save().await.unwrap();

    let contents = tokio::fs::read_to_string(config.config_path.clone())
        .await
        .unwrap();
    let stored: Config = toml::from_str(&contents).unwrap();
    let store = crate::security::SecretStore::new(&dir, true);

    let root_encrypted = stored.api_key.as_deref().unwrap();
    assert!(crate::security::SecretStore::is_encrypted(root_encrypted));
    assert_eq!(store.decrypt(root_encrypted).unwrap(), "root-credential");

    let composio_encrypted = stored.composio.api_key.as_deref().unwrap();
    assert!(crate::security::SecretStore::is_encrypted(
        composio_encrypted
    ));
    assert_eq!(
        store.decrypt(composio_encrypted).unwrap(),
        "composio-credential"
    );

    let browser_encrypted = stored.browser.computer_use.api_key.as_deref().unwrap();
    assert!(crate::security::SecretStore::is_encrypted(
        browser_encrypted
    ));
    assert_eq!(
        store.decrypt(browser_encrypted).unwrap(),
        "browser-credential"
    );

    let web_search_encrypted = stored.web_search.brave_api_key.as_deref().unwrap();
    assert!(crate::security::SecretStore::is_encrypted(
        web_search_encrypted
    ));
    assert_eq!(
        store.decrypt(web_search_encrypted).unwrap(),
        "brave-credential"
    );

    let worker = stored.agents.get("worker").unwrap();
    let worker_encrypted = worker.api_key.as_deref().unwrap();
    assert!(crate::security::SecretStore::is_encrypted(worker_encrypted));
    assert_eq!(store.decrypt(worker_encrypted).unwrap(), "agent-credential");

    let storage_db_url = stored.storage.provider.config.db_url.as_deref().unwrap();
    assert!(crate::security::SecretStore::is_encrypted(storage_db_url));
    assert_eq!(
        store.decrypt(storage_db_url).unwrap(),
        "postgres://user:pw@host/db"
    );

    let feishu = stored.channels_config.feishu.as_ref().unwrap();
    assert!(crate::security::SecretStore::is_encrypted(
        &feishu.app_secret
    ));
    assert_eq!(store.decrypt(&feishu.app_secret).unwrap(), "feishu-secret");
    assert!(
        feishu
            .encrypt_key
            .as_deref()
            .is_some_and(crate::security::SecretStore::is_encrypted)
    );
    assert_eq!(
        store
            .decrypt(feishu.encrypt_key.as_deref().unwrap())
            .unwrap(),
        "feishu-encrypt"
    );
    assert!(
        feishu
            .verification_token
            .as_deref()
            .is_some_and(crate::security::SecretStore::is_encrypted)
    );
    assert_eq!(
        store
            .decrypt(feishu.verification_token.as_deref().unwrap())
            .unwrap(),
        "feishu-verify"
    );

    let _ = fs::remove_dir_all(&dir).await;
}

#[tokio::test]
async fn config_save_atomic_cleanup() {
    let dir = std::env::temp_dir().join(format!("rain_test_config_{}", uuid::Uuid::new_v4()));
    fs::create_dir_all(&dir).await.unwrap();

    let config_path = dir.join("config.toml");
    let mut config = Config::default();
    config.workspace_dir = dir.join("workspace");
    config.config_path = config_path.clone();
    config.default_model = Some("model-a".into());
    config.save().await.unwrap();
    assert!(config_path.exists());

    config.default_model = Some("model-b".into());
    config.save().await.unwrap();

    let contents = tokio::fs::read_to_string(&config_path).await.unwrap();
    assert!(contents.contains("model-b"));

    let names: Vec<String> = ReadDirStream::new(fs::read_dir(&dir).await.unwrap())
        .map(|entry| entry.unwrap().file_name().to_string_lossy().to_string())
        .collect()
        .await;
    assert!(!names.iter().any(|name| name.contains(".tmp-")));
    assert!(!names.iter().any(|name| name.ends_with(".bak")));

    let _ = fs::remove_dir_all(&dir).await;
}

// ── Telegram / Discord config ────────────────────────────

#[test]
async fn telegram_config_serde() {
    let tc = TelegramConfig {
        bot_token: "123:XYZ".into(),
        allowed_users: vec!["alice".into(), "bob".into()],
        stream_mode: StreamMode::Partial,
        draft_update_interval_ms: 500,
        interrupt_on_new_message: true,
        mention_only: false,
        ack_reactions: None,
        proxy_url: None,
    };
    let json = serde_json::to_string(&tc).unwrap();
    let parsed: TelegramConfig = serde_json::from_str(&json).unwrap();
    assert_eq!(parsed.bot_token, "123:XYZ");
    assert_eq!(parsed.allowed_users.len(), 2);
    assert_eq!(parsed.stream_mode, StreamMode::Partial);
    assert_eq!(parsed.draft_update_interval_ms, 500);
    assert!(parsed.interrupt_on_new_message);
}

#[test]
async fn telegram_config_defaults_stream_off() {
    let json = r#"{"bot_token":"tok","allowed_users":[]}"#;
    let parsed: TelegramConfig = serde_json::from_str(json).unwrap();
    assert_eq!(parsed.stream_mode, StreamMode::Off);
    assert_eq!(parsed.draft_update_interval_ms, 1000);
    assert!(!parsed.interrupt_on_new_message);
}

#[test]
async fn discord_config_serde() {
    let dc = DiscordConfig {
        bot_token: "discord-token".into(),
        guild_id: Some("12345".into()),
        allowed_users: vec![],
        listen_to_bots: false,
        interrupt_on_new_message: false,
        mention_only: false,
        proxy_url: None,
    };
    let json = serde_json::to_string(&dc).unwrap();
    let parsed: DiscordConfig = serde_json::from_str(&json).unwrap();
    assert_eq!(parsed.bot_token, "discord-token");
    assert_eq!(parsed.guild_id.as_deref(), Some("12345"));
}

#[test]
async fn discord_config_optional_guild() {
    let dc = DiscordConfig {
        bot_token: "tok".into(),
        guild_id: None,
        allowed_users: vec![],
        listen_to_bots: false,
        interrupt_on_new_message: false,
        mention_only: false,
        proxy_url: None,
    };
    let json = serde_json::to_string(&dc).unwrap();
    let parsed: DiscordConfig = serde_json::from_str(&json).unwrap();
    assert!(parsed.guild_id.is_none());
}

// ── iMessage / Matrix config ────────────────────────────

#[test]
async fn imessage_config_serde() {
    let ic = IMessageConfig {
        allowed_contacts: vec!["+1234567890".into(), "user@icloud.com".into()],
    };
    let json = serde_json::to_string(&ic).unwrap();
    let parsed: IMessageConfig = serde_json::from_str(&json).unwrap();
    assert_eq!(parsed.allowed_contacts.len(), 2);
    assert_eq!(parsed.allowed_contacts[0], "+1234567890");
}

#[test]
async fn imessage_config_empty_contacts() {
    let ic = IMessageConfig {
        allowed_contacts: vec![],
    };
    let json = serde_json::to_string(&ic).unwrap();
    let parsed: IMessageConfig = serde_json::from_str(&json).unwrap();
    assert!(parsed.allowed_contacts.is_empty());
}

#[test]
async fn imessage_config_wildcard() {
    let ic = IMessageConfig {
        allowed_contacts: vec!["*".into()],
    };
    let toml_str = toml::to_string(&ic).unwrap();
    let parsed: IMessageConfig = toml::from_str(&toml_str).unwrap();
    assert_eq!(parsed.allowed_contacts, vec!["*"]);
}

#[test]
async fn matrix_config_serde() {
    let mc = MatrixConfig {
        homeserver: "https://matrix.org".into(),
        access_token: "syt_token_abc".into(),
        user_id: Some("@bot:matrix.org".into()),
        device_id: Some("DEVICE123".into()),
        room_id: "!room123:matrix.org".into(),
        allowed_users: vec!["@user:matrix.org".into()],
        interrupt_on_new_message: false,
    };
    let json = serde_json::to_string(&mc).unwrap();
    let parsed: MatrixConfig = serde_json::from_str(&json).unwrap();
    assert_eq!(parsed.homeserver, "https://matrix.org");
    assert_eq!(parsed.access_token, "syt_token_abc");
    assert_eq!(parsed.user_id.as_deref(), Some("@bot:matrix.org"));
    assert_eq!(parsed.device_id.as_deref(), Some("DEVICE123"));
    assert_eq!(parsed.room_id, "!room123:matrix.org");
    assert_eq!(parsed.allowed_users.len(), 1);
}

#[test]
async fn matrix_config_toml_roundtrip() {
    let mc = MatrixConfig {
        homeserver: "https://synapse.local:8448".into(),
        access_token: "tok".into(),
        user_id: None,
        device_id: None,
        room_id: "!abc:synapse.local".into(),
        allowed_users: vec!["@admin:synapse.local".into(), "*".into()],
        interrupt_on_new_message: false,
    };
    let toml_str = toml::to_string(&mc).unwrap();
    let parsed: MatrixConfig = toml::from_str(&toml_str).unwrap();
    assert_eq!(parsed.homeserver, "https://synapse.local:8448");
    assert_eq!(parsed.allowed_users.len(), 2);
}

#[test]
async fn matrix_config_backward_compatible_without_session_hints() {
    let toml = r#"
homeserver = "https://matrix.org"
access_token = "tok"
room_id = "!ops:matrix.org"
allowed_users = ["@ops:matrix.org"]
"#;

    let parsed: MatrixConfig = toml::from_str(toml).unwrap();
    assert_eq!(parsed.homeserver, "https://matrix.org");
    assert!(parsed.user_id.is_none());
    assert!(parsed.device_id.is_none());
}

#[test]
async fn signal_config_serde() {
    let sc = SignalConfig {
        http_url: "http://127.0.0.1:8686".into(),
        account: "+1234567890".into(),
        group_id: Some("group123".into()),
        allowed_from: vec!["+1111111111".into()],
        ignore_attachments: true,
        ignore_stories: false,
        proxy_url: None,
    };
    let json = serde_json::to_string(&sc).unwrap();
    let parsed: SignalConfig = serde_json::from_str(&json).unwrap();
    assert_eq!(parsed.http_url, "http://127.0.0.1:8686");
    assert_eq!(parsed.account, "+1234567890");
    assert_eq!(parsed.group_id.as_deref(), Some("group123"));
    assert_eq!(parsed.allowed_from.len(), 1);
    assert!(parsed.ignore_attachments);
    assert!(!parsed.ignore_stories);
}

#[test]
async fn signal_config_toml_roundtrip() {
    let sc = SignalConfig {
        http_url: "http://localhost:8080".into(),
        account: "+9876543210".into(),
        group_id: None,
        allowed_from: vec!["*".into()],
        ignore_attachments: false,
        ignore_stories: true,
        proxy_url: None,
    };
    let toml_str = toml::to_string(&sc).unwrap();
    let parsed: SignalConfig = toml::from_str(&toml_str).unwrap();
    assert_eq!(parsed.http_url, "http://localhost:8080");
    assert_eq!(parsed.account, "+9876543210");
    assert!(parsed.group_id.is_none());
    assert!(parsed.ignore_stories);
}

#[test]
async fn signal_config_defaults() {
    let json = r#"{"http_url":"http://127.0.0.1:8686","account":"+1234567890"}"#;
    let parsed: SignalConfig = serde_json::from_str(json).unwrap();
    assert!(parsed.group_id.is_none());
    assert!(parsed.allowed_from.is_empty());
    assert!(!parsed.ignore_attachments);
    assert!(!parsed.ignore_stories);
}

#[test]
async fn channels_config_with_imessage_and_matrix() {
    let c = ChannelsConfig {
        cli: true,
        telegram: None,
        discord: None,
        slack: None,
        mattermost: None,
        webhook: None,
        imessage: Some(IMessageConfig {
            allowed_contacts: vec!["+1".into()],
        }),
        matrix: Some(MatrixConfig {
            homeserver: "https://m.org".into(),
            access_token: "tok".into(),
            user_id: None,
            device_id: None,
            room_id: "!r:m".into(),
            allowed_users: vec!["@u:m".into()],
            interrupt_on_new_message: false,
        }),
        signal: None,
        whatsapp: None,
        linq: None,
        wati: None,
        nextcloud_talk: None,
        email: None,
        irc: None,
        lark: None,
        feishu: None,
        dingtalk: None,
        wecom: None,
        qq: None,
        twitter: None,
        mochat: None,
        #[cfg(feature = "channel-nostr")]
        nostr: None,
        clawdtalk: None,
        reddit: None,
        bluesky: None,
        message_timeout_secs: 300,
        ack_reactions: true,
        show_tool_calls: true,
        session_persistence: true,
        session_backend: default_session_backend(),
        session_ttl_hours: 0,
    };
    let toml_str = toml::to_string_pretty(&c).unwrap();
    let parsed: ChannelsConfig = toml::from_str(&toml_str).unwrap();
    assert!(parsed.imessage.is_some());
    assert!(parsed.matrix.is_some());
    assert_eq!(parsed.imessage.unwrap().allowed_contacts, vec!["+1"]);
    assert_eq!(parsed.matrix.unwrap().homeserver, "https://m.org");
}

#[test]
async fn channels_config_default_has_no_imessage_matrix() {
    let c = ChannelsConfig::default();
    assert!(c.imessage.is_none());
    assert!(c.matrix.is_none());
}

// ── Edge cases: serde(default) for allowed_users ─────────

#[test]
async fn discord_config_deserializes_without_allowed_users() {
    // Old configs won't have allowed_users — serde(default) should fill vec![]
    let json = r#"{"bot_token":"tok","guild_id":"123"}"#;
    let parsed: DiscordConfig = serde_json::from_str(json).unwrap();
    assert!(parsed.allowed_users.is_empty());
}

#[test]
async fn discord_config_deserializes_with_allowed_users() {
    let json = r#"{"bot_token":"tok","guild_id":"123","allowed_users":["111","222"]}"#;
    let parsed: DiscordConfig = serde_json::from_str(json).unwrap();
    assert_eq!(parsed.allowed_users, vec!["111", "222"]);
}

#[test]
async fn slack_config_deserializes_without_allowed_users() {
    let json = r#"{"bot_token":"xoxb-tok"}"#;
    let parsed: SlackConfig = serde_json::from_str(json).unwrap();
    assert!(parsed.allowed_users.is_empty());
    assert!(!parsed.interrupt_on_new_message);
    assert_eq!(parsed.thread_replies, None);
    assert!(!parsed.mention_only);
}

#[test]
async fn slack_config_deserializes_with_allowed_users() {
    let json = r#"{"bot_token":"xoxb-tok","allowed_users":["U111"]}"#;
    let parsed: SlackConfig = serde_json::from_str(json).unwrap();
    assert_eq!(parsed.allowed_users, vec!["U111"]);
    assert!(!parsed.interrupt_on_new_message);
    assert_eq!(parsed.thread_replies, None);
    assert!(!parsed.mention_only);
}

#[test]
async fn slack_config_deserializes_with_mention_only() {
    let json = r#"{"bot_token":"xoxb-tok","mention_only":true}"#;
    let parsed: SlackConfig = serde_json::from_str(json).unwrap();
    assert!(parsed.mention_only);
    assert!(!parsed.interrupt_on_new_message);
    assert_eq!(parsed.thread_replies, None);
}

#[test]
async fn slack_config_deserializes_interrupt_on_new_message() {
    let json = r#"{"bot_token":"xoxb-tok","interrupt_on_new_message":true}"#;
    let parsed: SlackConfig = serde_json::from_str(json).unwrap();
    assert!(parsed.interrupt_on_new_message);
    assert_eq!(parsed.thread_replies, None);
    assert!(!parsed.mention_only);
}

#[test]
async fn slack_config_deserializes_thread_replies() {
    let json = r#"{"bot_token":"xoxb-tok","thread_replies":false}"#;
    let parsed: SlackConfig = serde_json::from_str(json).unwrap();
    assert_eq!(parsed.thread_replies, Some(false));
    assert!(!parsed.interrupt_on_new_message);
    assert!(!parsed.mention_only);
}

#[test]
async fn discord_config_default_interrupt_on_new_message_is_false() {
    let json = r#"{"bot_token":"tok"}"#;
    let parsed: DiscordConfig = serde_json::from_str(json).unwrap();
    assert!(!parsed.interrupt_on_new_message);
}

#[test]
async fn discord_config_deserializes_interrupt_on_new_message_true() {
    let json = r#"{"bot_token":"tok","interrupt_on_new_message":true}"#;
    let parsed: DiscordConfig = serde_json::from_str(json).unwrap();
    assert!(parsed.interrupt_on_new_message);
}

#[test]
async fn discord_config_toml_backward_compat() {
    let toml_str = r#"
bot_token = "tok"
guild_id = "123"
"#;
    let parsed: DiscordConfig = toml::from_str(toml_str).unwrap();
    assert!(parsed.allowed_users.is_empty());
    assert_eq!(parsed.bot_token, "tok");
}

#[test]
async fn slack_config_toml_backward_compat() {
    let toml_str = r#"
bot_token = "xoxb-tok"
channel_id = "C123"
"#;
    let parsed: SlackConfig = toml::from_str(toml_str).unwrap();
    assert!(parsed.allowed_users.is_empty());
    assert!(!parsed.interrupt_on_new_message);
    assert_eq!(parsed.thread_replies, None);
    assert!(!parsed.mention_only);
    assert_eq!(parsed.channel_id.as_deref(), Some("C123"));
}

#[test]
async fn mattermost_config_default_interrupt_on_new_message_is_false() {
    let json = r#"{"url":"https://mm.example.com","bot_token":"tok"}"#;
    let parsed: MattermostConfig = serde_json::from_str(json).unwrap();
    assert!(!parsed.interrupt_on_new_message);
}

#[test]
async fn mattermost_config_deserializes_interrupt_on_new_message_true() {
    let json =
        r#"{"url":"https://mm.example.com","bot_token":"tok","interrupt_on_new_message":true}"#;
    let parsed: MattermostConfig = serde_json::from_str(json).unwrap();
    assert!(parsed.interrupt_on_new_message);
}

#[test]
async fn webhook_config_with_secret() {
    let json = r#"{"port":8080,"secret":"my-secret-key"}"#;
    let parsed: WebhookConfig = serde_json::from_str(json).unwrap();
    assert_eq!(parsed.secret.as_deref(), Some("my-secret-key"));
}

#[test]
async fn webhook_config_without_secret() {
    let json = r#"{"port":8080}"#;
    let parsed: WebhookConfig = serde_json::from_str(json).unwrap();
    assert!(parsed.secret.is_none());
    assert_eq!(parsed.port, 8080);
}

// ── WhatsApp config ──────────────────────────────────────

#[test]
async fn whatsapp_config_serde() {
    let wc = WhatsAppConfig {
        access_token: Some("EAABx...".into()),
        phone_number_id: Some("123456789".into()),
        verify_token: Some("my-verify-token".into()),
        app_secret: None,
        session_path: None,
        pair_phone: None,
        pair_code: None,
        allowed_numbers: vec!["+1234567890".into(), "+9876543210".into()],
        mode: WhatsAppWebMode::default(),
        dm_policy: WhatsAppChatPolicy::default(),
        group_policy: WhatsAppChatPolicy::default(),
        self_chat_mode: false,
        proxy_url: None,
    };
    let json = serde_json::to_string(&wc).unwrap();
    let parsed: WhatsAppConfig = serde_json::from_str(&json).unwrap();
    assert_eq!(parsed.access_token, Some("EAABx...".into()));
    assert_eq!(parsed.phone_number_id, Some("123456789".into()));
    assert_eq!(parsed.verify_token, Some("my-verify-token".into()));
    assert_eq!(parsed.allowed_numbers.len(), 2);
}

#[test]
async fn whatsapp_config_toml_roundtrip() {
    let wc = WhatsAppConfig {
        access_token: Some("tok".into()),
        phone_number_id: Some("12345".into()),
        verify_token: Some("verify".into()),
        app_secret: Some("secret123".into()),
        session_path: None,
        pair_phone: None,
        pair_code: None,
        allowed_numbers: vec!["+1".into()],
        mode: WhatsAppWebMode::default(),
        dm_policy: WhatsAppChatPolicy::default(),
        group_policy: WhatsAppChatPolicy::default(),
        self_chat_mode: false,
        proxy_url: None,
    };
    let toml_str = toml::to_string(&wc).unwrap();
    let parsed: WhatsAppConfig = toml::from_str(&toml_str).unwrap();
    assert_eq!(parsed.phone_number_id, Some("12345".into()));
    assert_eq!(parsed.allowed_numbers, vec!["+1"]);
}

#[test]
async fn whatsapp_config_deserializes_without_allowed_numbers() {
    let json = r#"{"access_token":"tok","phone_number_id":"123","verify_token":"ver"}"#;
    let parsed: WhatsAppConfig = serde_json::from_str(json).unwrap();
    assert!(parsed.allowed_numbers.is_empty());
}

#[test]
async fn whatsapp_config_wildcard_allowed() {
    let wc = WhatsAppConfig {
        access_token: Some("tok".into()),
        phone_number_id: Some("123".into()),
        verify_token: Some("ver".into()),
        app_secret: None,
        session_path: None,
        pair_phone: None,
        pair_code: None,
        allowed_numbers: vec!["*".into()],
        mode: WhatsAppWebMode::default(),
        dm_policy: WhatsAppChatPolicy::default(),
        group_policy: WhatsAppChatPolicy::default(),
        self_chat_mode: false,
        proxy_url: None,
    };
    let toml_str = toml::to_string(&wc).unwrap();
    let parsed: WhatsAppConfig = toml::from_str(&toml_str).unwrap();
    assert_eq!(parsed.allowed_numbers, vec!["*"]);
}

#[test]
async fn whatsapp_config_backend_type_cloud_precedence_when_ambiguous() {
    let wc = WhatsAppConfig {
        access_token: Some("tok".into()),
        phone_number_id: Some("123".into()),
        verify_token: Some("ver".into()),
        app_secret: None,
        session_path: Some("~/.R.A.I.N./state/whatsapp-web/session.db".into()),
        pair_phone: None,
        pair_code: None,
        allowed_numbers: vec!["+1".into()],
        mode: WhatsAppWebMode::default(),
        dm_policy: WhatsAppChatPolicy::default(),
        group_policy: WhatsAppChatPolicy::default(),
        self_chat_mode: false,
        proxy_url: None,
    };
    assert!(wc.is_ambiguous_config());
    assert_eq!(wc.backend_type(), "cloud");
}

#[test]
async fn whatsapp_config_backend_type_web() {
    let wc = WhatsAppConfig {
        access_token: None,
        phone_number_id: None,
        verify_token: None,
        app_secret: None,
        session_path: Some("~/.R.A.I.N./state/whatsapp-web/session.db".into()),
        pair_phone: None,
        pair_code: None,
        allowed_numbers: vec![],
        mode: WhatsAppWebMode::default(),
        dm_policy: WhatsAppChatPolicy::default(),
        group_policy: WhatsAppChatPolicy::default(),
        self_chat_mode: false,
        proxy_url: None,
    };
    assert!(!wc.is_ambiguous_config());
    assert_eq!(wc.backend_type(), "web");
}

#[test]
async fn channels_config_with_whatsapp() {
    let c = ChannelsConfig {
        cli: true,
        telegram: None,
        discord: None,
        slack: None,
        mattermost: None,
        webhook: None,
        imessage: None,
        matrix: None,
        signal: None,
        whatsapp: Some(WhatsAppConfig {
            access_token: Some("tok".into()),
            phone_number_id: Some("123".into()),
            verify_token: Some("ver".into()),
            app_secret: None,
            session_path: None,
            pair_phone: None,
            pair_code: None,
            allowed_numbers: vec!["+1".into()],
            mode: WhatsAppWebMode::default(),
            dm_policy: WhatsAppChatPolicy::default(),
            group_policy: WhatsAppChatPolicy::default(),
            self_chat_mode: false,
            proxy_url: None,
        }),
        linq: None,
        wati: None,
        nextcloud_talk: None,
        email: None,
        irc: None,
        lark: None,
        feishu: None,
        dingtalk: None,
        wecom: None,
        qq: None,
        twitter: None,
        mochat: None,
        #[cfg(feature = "channel-nostr")]
        nostr: None,
        clawdtalk: None,
        reddit: None,
        bluesky: None,
        message_timeout_secs: 300,
        ack_reactions: true,
        show_tool_calls: true,
        session_persistence: true,
        session_backend: default_session_backend(),
        session_ttl_hours: 0,
    };
    let toml_str = toml::to_string_pretty(&c).unwrap();
    let parsed: ChannelsConfig = toml::from_str(&toml_str).unwrap();
    assert!(parsed.whatsapp.is_some());
    let wa = parsed.whatsapp.unwrap();
    assert_eq!(wa.phone_number_id, Some("123".into()));
    assert_eq!(wa.allowed_numbers, vec!["+1"]);
}

#[test]
async fn channels_config_default_has_no_whatsapp() {
    let c = ChannelsConfig::default();
    assert!(c.whatsapp.is_none());
}

#[test]
async fn channels_config_default_has_no_nextcloud_talk() {
    let c = ChannelsConfig::default();
    assert!(c.nextcloud_talk.is_none());
}

// ══════════════════════════════════════════════════════════
// SECURITY CHECKLIST TESTS — Gateway config
// ══════════════════════════════════════════════════════════

#[test]
async fn checklist_gateway_default_requires_pairing() {
    let g = GatewayConfig::default();
    assert!(g.require_pairing, "Pairing must be required by default");
}

#[test]
async fn checklist_gateway_default_blocks_public_bind() {
    let g = GatewayConfig::default();
    assert!(
        !g.allow_public_bind,
        "Public bind must be blocked by default"
    );
}

#[test]
async fn checklist_gateway_default_no_tokens() {
    let g = GatewayConfig::default();
    assert!(
        g.paired_tokens.is_empty(),
        "No pre-paired tokens by default"
    );
    assert_eq!(g.pair_rate_limit_per_minute, 10);
    assert_eq!(g.webhook_rate_limit_per_minute, 60);
    assert!(!g.trust_forwarded_headers);
    assert_eq!(g.rate_limit_max_keys, 10_000);
    assert_eq!(g.idempotency_ttl_secs, 300);
    assert_eq!(g.idempotency_max_keys, 10_000);
}

#[test]
async fn checklist_gateway_cli_default_host_is_localhost() {
    // The CLI default for --host is 127.0.0.1 (checked in main.rs)
    // Here we verify the config default matches
    let c = Config::default();
    assert!(
        c.gateway.require_pairing,
        "Config default must require pairing"
    );
    assert!(
        !c.gateway.allow_public_bind,
        "Config default must block public bind"
    );
}

#[test]
async fn checklist_gateway_serde_roundtrip() {
    let g = GatewayConfig {
        port: 42617,
        host: "127.0.0.1".into(),
        require_pairing: true,
        allow_public_bind: false,
        paired_tokens: vec!["zc_test_token".into()],
        pair_rate_limit_per_minute: 12,
        webhook_rate_limit_per_minute: 80,
        trust_forwarded_headers: true,
        path_prefix: Some("/R.A.I.N.".into()),
        rate_limit_max_keys: 2048,
        idempotency_ttl_secs: 600,
        idempotency_max_keys: 4096,
        session_persistence: true,
        session_ttl_hours: 0,
        pairing_dashboard: PairingDashboardConfig::default(),
    };
    let toml_str = toml::to_string(&g).unwrap();
    let parsed: GatewayConfig = toml::from_str(&toml_str).unwrap();
    assert!(parsed.require_pairing);
    assert!(parsed.session_persistence);
    assert_eq!(parsed.session_ttl_hours, 0);
    assert!(!parsed.allow_public_bind);
    assert_eq!(parsed.paired_tokens, vec!["zc_test_token"]);
    assert_eq!(parsed.pair_rate_limit_per_minute, 12);
    assert_eq!(parsed.webhook_rate_limit_per_minute, 80);
    assert!(parsed.trust_forwarded_headers);
    assert_eq!(parsed.path_prefix.as_deref(), Some("/R.A.I.N."));
    assert_eq!(parsed.rate_limit_max_keys, 2048);
    assert_eq!(parsed.idempotency_ttl_secs, 600);
    assert_eq!(parsed.idempotency_max_keys, 4096);
}

#[test]
async fn checklist_gateway_backward_compat_no_gateway_section() {
    // Old configs without [gateway] should get secure defaults
    let minimal = r#"
workspace_dir = "/tmp/ws"
config_path = "/tmp/config.toml"
default_temperature = 0.7
"#;
    let parsed = parse_test_config(minimal);
    assert!(
        parsed.gateway.require_pairing,
        "Missing [gateway] must default to require_pairing=true"
    );
    assert!(
        !parsed.gateway.allow_public_bind,
        "Missing [gateway] must default to allow_public_bind=false"
    );
}

#[test]
async fn checklist_autonomy_default_is_workspace_scoped() {
    let a = AutonomyConfig::default();
    assert!(a.workspace_only, "Default autonomy must be workspace_only");
    assert!(
        a.forbidden_paths.contains(&"/etc".to_string()),
        "Must block /etc"
    );
    assert!(
        a.forbidden_paths.contains(&"/proc".to_string()),
        "Must block /proc"
    );
    assert!(
        a.forbidden_paths.contains(&"~/.ssh".to_string()),
        "Must block ~/.ssh"
    );
}

// ══════════════════════════════════════════════════════════
// COMPOSIO CONFIG TESTS
// ══════════════════════════════════════════════════════════

#[test]
async fn composio_config_default_disabled() {
    let c = ComposioConfig::default();
    assert!(!c.enabled, "Composio must be disabled by default");
    assert!(c.api_key.is_none(), "No API key by default");
    assert_eq!(c.entity_id, "default");
}

#[test]
async fn composio_config_serde_roundtrip() {
    let c = ComposioConfig {
        enabled: true,
        api_key: Some("comp-key-123".into()),
        entity_id: "user42".into(),
    };
    let toml_str = toml::to_string(&c).unwrap();
    let parsed: ComposioConfig = toml::from_str(&toml_str).unwrap();
    assert!(parsed.enabled);
    assert_eq!(parsed.api_key.as_deref(), Some("comp-key-123"));
    assert_eq!(parsed.entity_id, "user42");
}

#[test]
async fn composio_config_backward_compat_missing_section() {
    let minimal = r#"
workspace_dir = "/tmp/ws"
config_path = "/tmp/config.toml"
default_temperature = 0.7
"#;
    let parsed = parse_test_config(minimal);
    assert!(
        !parsed.composio.enabled,
        "Missing [composio] must default to disabled"
    );
    assert!(parsed.composio.api_key.is_none());
}

#[test]
async fn composio_config_partial_toml() {
    let toml_str = r"
enabled = true
";
    let parsed: ComposioConfig = toml::from_str(toml_str).unwrap();
    assert!(parsed.enabled);
    assert!(parsed.api_key.is_none());
    assert_eq!(parsed.entity_id, "default");
}

#[test]
async fn composio_config_enable_alias_supported() {
    let toml_str = r"
enable = true
";
    let parsed: ComposioConfig = toml::from_str(toml_str).unwrap();
    assert!(parsed.enabled);
    assert!(parsed.api_key.is_none());
    assert_eq!(parsed.entity_id, "default");
}

// ══════════════════════════════════════════════════════════
// SECRETS CONFIG TESTS
// ══════════════════════════════════════════════════════════

#[test]
async fn secrets_config_default_encrypts() {
    let s = SecretsConfig::default();
    assert!(s.encrypt, "Encryption must be enabled by default");
}

#[test]
async fn secrets_config_serde_roundtrip() {
    let s = SecretsConfig { encrypt: false };
    let toml_str = toml::to_string(&s).unwrap();
    let parsed: SecretsConfig = toml::from_str(&toml_str).unwrap();
    assert!(!parsed.encrypt);
}

#[test]
async fn secrets_config_backward_compat_missing_section() {
    let minimal = r#"
workspace_dir = "/tmp/ws"
config_path = "/tmp/config.toml"
default_temperature = 0.7
"#;
    let parsed = parse_test_config(minimal);
    assert!(
        parsed.secrets.encrypt,
        "Missing [secrets] must default to encrypt=true"
    );
}

#[test]
async fn config_default_has_composio_and_secrets() {
    let c = Config::default();
    assert!(!c.composio.enabled);
    assert!(c.composio.api_key.is_none());
    assert!(c.secrets.encrypt);
    assert!(!c.browser.enabled);
    assert!(c.browser.allowed_domains.is_empty());
}

#[test]
async fn browser_config_default_disabled() {
    let b = BrowserConfig::default();
    assert!(!b.enabled);
    assert!(b.allowed_domains.is_empty());
    assert_eq!(b.backend, "agent_browser");
    assert!(b.native_headless);
    assert_eq!(b.native_webdriver_url, "http://127.0.0.1:9515");
    assert!(b.native_chrome_path.is_none());
    assert_eq!(b.computer_use.endpoint, "http://127.0.0.1:8787/v1/actions");
    assert_eq!(b.computer_use.timeout_ms, 15_000);
    assert!(!b.computer_use.allow_remote_endpoint);
    assert!(b.computer_use.window_allowlist.is_empty());
    assert!(b.computer_use.max_coordinate_x.is_none());
    assert!(b.computer_use.max_coordinate_y.is_none());
}

#[test]
async fn browser_config_serde_roundtrip() {
    let b = BrowserConfig {
        enabled: true,
        allowed_domains: vec!["example.com".into(), "docs.example.com".into()],
        session_name: None,
        backend: "auto".into(),
        native_headless: false,
        native_webdriver_url: "http://localhost:4444".into(),
        native_chrome_path: Some("/usr/bin/chromium".into()),
        computer_use: BrowserComputerUseConfig {
            endpoint: "https://computer-use.example.com/v1/actions".into(),
            api_key: Some("test-token".into()),
            timeout_ms: 8_000,
            allow_remote_endpoint: true,
            window_allowlist: vec!["Chrome".into(), "Visual Studio Code".into()],
            max_coordinate_x: Some(3840),
            max_coordinate_y: Some(2160),
        },
    };
    let toml_str = toml::to_string(&b).unwrap();
    let parsed: BrowserConfig = toml::from_str(&toml_str).unwrap();
    assert!(parsed.enabled);
    assert_eq!(parsed.allowed_domains.len(), 2);
    assert_eq!(parsed.allowed_domains[0], "example.com");
    assert_eq!(parsed.backend, "auto");
    assert!(!parsed.native_headless);
    assert_eq!(parsed.native_webdriver_url, "http://localhost:4444");
    assert_eq!(
        parsed.native_chrome_path.as_deref(),
        Some("/usr/bin/chromium")
    );
    assert_eq!(
        parsed.computer_use.endpoint,
        "https://computer-use.example.com/v1/actions"
    );
    assert_eq!(parsed.computer_use.api_key.as_deref(), Some("test-token"));
    assert_eq!(parsed.computer_use.timeout_ms, 8_000);
    assert!(parsed.computer_use.allow_remote_endpoint);
    assert_eq!(parsed.computer_use.window_allowlist.len(), 2);
    assert_eq!(parsed.computer_use.max_coordinate_x, Some(3840));
    assert_eq!(parsed.computer_use.max_coordinate_y, Some(2160));
}

#[test]
async fn browser_config_backward_compat_missing_section() {
    let minimal = r#"
workspace_dir = "/tmp/ws"
config_path = "/tmp/config.toml"
default_temperature = 0.7
"#;
    let parsed = parse_test_config(minimal);
    assert!(!parsed.browser.enabled);
    assert!(parsed.browser.allowed_domains.is_empty());
}

// ── Environment variable overrides (Docker support) ─────────

async fn env_override_lock() -> MutexGuard<'static, ()> {
    static ENV_OVERRIDE_TEST_LOCK: Mutex<()> = Mutex::const_new(());
    ENV_OVERRIDE_TEST_LOCK.lock().await
}

fn clear_proxy_env_test_vars() {
    for key in [
        "rain_PROXY_ENABLED",
        "rain_HTTP_PROXY",
        "rain_HTTPS_PROXY",
        "rain_ALL_PROXY",
        "rain_NO_PROXY",
        "rain_PROXY_SCOPE",
        "rain_PROXY_SERVICES",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
    ] {
        // SAFETY: single-threaded test/init context
        unsafe {
            std::env::remove_var(key);
        }
    }
}

#[test]
async fn env_override_api_key() {
    let _env_guard = env_override_lock().await;
    let mut config = Config::default();
    assert!(config.api_key.is_none());

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_API_KEY", "sk-test-env-key");
    }
    config.apply_env_overrides();
    assert_eq!(config.api_key.as_deref(), Some("sk-test-env-key"));

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_API_KEY");
    }
}

#[test]
async fn env_override_api_key_fallback() {
    let _env_guard = env_override_lock().await;
    let mut config = Config::default();

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_API_KEY");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("API_KEY", "sk-fallback-key");
    }
    config.apply_env_overrides();
    assert_eq!(config.api_key.as_deref(), Some("sk-fallback-key"));

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("API_KEY");
    }
}

#[test]
async fn env_override_provider() {
    let _env_guard = env_override_lock().await;
    let mut config = Config::default();

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_PROVIDER", "anthropic");
    }
    config.apply_env_overrides();
    assert_eq!(config.default_provider.as_deref(), Some("anthropic"));

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_PROVIDER");
    }
}

#[test]
async fn env_override_model_provider_alias() {
    let _env_guard = env_override_lock().await;
    let mut config = Config::default();

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_PROVIDER");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_MODEL_PROVIDER", "openai-codex");
    }
    config.apply_env_overrides();
    assert_eq!(config.default_provider.as_deref(), Some("openai-codex"));

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_MODEL_PROVIDER");
    }
}

#[test]
async fn toml_supports_model_provider_and_model_alias_fields() {
    let raw = r#"
default_temperature = 0.7
model_provider = "sub2api"
model = "gpt-5.3-codex"

[model_providers.sub2api]
name = "sub2api"
base_url = "https://api.tonsof.blue/v1"
wire_api = "responses"
requires_openai_auth = true
"#;

    let parsed = parse_test_config(raw);
    assert_eq!(parsed.default_provider.as_deref(), Some("sub2api"));
    assert_eq!(parsed.default_model.as_deref(), Some("gpt-5.3-codex"));
    let profile = parsed
        .model_providers
        .get("sub2api")
        .expect("profile should exist");
    assert_eq!(profile.wire_api.as_deref(), Some("responses"));
    assert!(profile.requires_openai_auth);
}

#[test]
async fn env_override_open_skills_enabled_and_dir() {
    let _env_guard = env_override_lock().await;
    let mut config = Config::default();
    assert!(!config.skills.open_skills_enabled);
    assert!(config.skills.open_skills_dir.is_none());
    assert_eq!(
        config.skills.prompt_injection_mode,
        SkillsPromptInjectionMode::Full
    );

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_OPEN_SKILLS_ENABLED", "true");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_OPEN_SKILLS_DIR", "/tmp/open-skills");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_SKILLS_ALLOW_SCRIPTS", "yes");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_SKILLS_PROMPT_MODE", "compact");
    }
    config.apply_env_overrides();

    assert!(config.skills.open_skills_enabled);
    assert!(config.skills.allow_scripts);
    assert_eq!(
        config.skills.open_skills_dir.as_deref(),
        Some("/tmp/open-skills")
    );
    assert_eq!(
        config.skills.prompt_injection_mode,
        SkillsPromptInjectionMode::Compact
    );

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_OPEN_SKILLS_ENABLED");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_OPEN_SKILLS_DIR");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_SKILLS_ALLOW_SCRIPTS");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_SKILLS_PROMPT_MODE");
    }
}

#[test]
async fn env_override_open_skills_enabled_invalid_value_keeps_existing_value() {
    let _env_guard = env_override_lock().await;
    let mut config = Config::default();
    config.skills.open_skills_enabled = true;
    config.skills.allow_scripts = true;
    config.skills.prompt_injection_mode = SkillsPromptInjectionMode::Compact;

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_OPEN_SKILLS_ENABLED", "maybe");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_SKILLS_ALLOW_SCRIPTS", "maybe");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_SKILLS_PROMPT_MODE", "invalid");
    }
    config.apply_env_overrides();

    assert!(config.skills.open_skills_enabled);
    assert!(config.skills.allow_scripts);
    assert_eq!(
        config.skills.prompt_injection_mode,
        SkillsPromptInjectionMode::Compact
    );
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_OPEN_SKILLS_ENABLED");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_SKILLS_ALLOW_SCRIPTS");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_SKILLS_PROMPT_MODE");
    }
}

#[test]
async fn env_override_provider_fallback() {
    let _env_guard = env_override_lock().await;
    let mut config = Config::default();

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_PROVIDER");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("PROVIDER", "openai");
    }
    config.apply_env_overrides();
    assert_eq!(config.default_provider.as_deref(), Some("openai"));

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("PROVIDER");
    }
}

#[test]
async fn env_override_provider_fallback_does_not_replace_non_default_provider() {
    let _env_guard = env_override_lock().await;
    let mut config = Config {
        default_provider: Some("custom:https://proxy.example.com/v1".to_string()),
        ..Config::default()
    };

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_PROVIDER");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("PROVIDER", "openrouter");
    }
    config.apply_env_overrides();
    assert_eq!(
        config.default_provider.as_deref(),
        Some("custom:https://proxy.example.com/v1")
    );

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("PROVIDER");
    }
}

#[test]
async fn env_override_zero_claw_provider_overrides_non_default_provider() {
    let _env_guard = env_override_lock().await;
    let mut config = Config {
        default_provider: Some("custom:https://proxy.example.com/v1".to_string()),
        ..Config::default()
    };

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_PROVIDER", "openrouter");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("PROVIDER", "anthropic");
    }
    config.apply_env_overrides();
    assert_eq!(config.default_provider.as_deref(), Some("openrouter"));

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_PROVIDER");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("PROVIDER");
    }
}

#[test]
async fn env_override_glm_api_key_for_regional_aliases() {
    let _env_guard = env_override_lock().await;
    let mut config = Config {
        default_provider: Some("glm-cn".to_string()),
        ..Config::default()
    };

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("GLM_API_KEY", "glm-regional-key");
    }
    config.apply_env_overrides();
    assert_eq!(config.api_key.as_deref(), Some("glm-regional-key"));

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("GLM_API_KEY");
    }
}

#[test]
async fn env_override_zai_api_key_for_regional_aliases() {
    let _env_guard = env_override_lock().await;
    let mut config = Config {
        default_provider: Some("zai-cn".to_string()),
        ..Config::default()
    };

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("ZAI_API_KEY", "zai-regional-key");
    }
    config.apply_env_overrides();
    assert_eq!(config.api_key.as_deref(), Some("zai-regional-key"));

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("ZAI_API_KEY");
    }
}

#[test]
async fn env_override_model() {
    let _env_guard = env_override_lock().await;
    let mut config = Config::default();

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_MODEL", "gpt-4o");
    }
    config.apply_env_overrides();
    assert_eq!(config.default_model.as_deref(), Some("gpt-4o"));

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_MODEL");
    }
}

#[test]
async fn model_provider_profile_maps_to_custom_endpoint() {
    let _env_guard = env_override_lock().await;
    let mut config = Config {
        default_provider: Some("sub2api".to_string()),
        model_providers: HashMap::from([(
            "sub2api".to_string(),
            ModelProviderConfig {
                name: Some("sub2api".to_string()),
                base_url: Some("https://api.tonsof.blue/v1".to_string()),
                wire_api: None,
                requires_openai_auth: false,
                azure_openai_resource: None,
                azure_openai_deployment: None,
                azure_openai_api_version: None,
                api_path: None,
            },
        )]),
        ..Config::default()
    };

    config.apply_env_overrides();
    assert_eq!(
        config.default_provider.as_deref(),
        Some("custom:https://api.tonsof.blue/v1")
    );
    assert_eq!(
        config.api_url.as_deref(),
        Some("https://api.tonsof.blue/v1")
    );
}

#[test]
async fn model_provider_profile_responses_uses_openai_codex_and_openai_key() {
    let _env_guard = env_override_lock().await;
    let mut config = Config {
        default_provider: Some("sub2api".to_string()),
        model_providers: HashMap::from([(
            "sub2api".to_string(),
            ModelProviderConfig {
                name: Some("sub2api".to_string()),
                base_url: Some("https://api.tonsof.blue".to_string()),
                wire_api: Some("responses".to_string()),
                requires_openai_auth: true,
                azure_openai_resource: None,
                azure_openai_deployment: None,
                azure_openai_api_version: None,
                api_path: None,
            },
        )]),
        api_key: None,
        ..Config::default()
    };

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("OPENAI_API_KEY", "sk-test-codex-key");
    }
    config.apply_env_overrides();
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("OPENAI_API_KEY");
    }

    assert_eq!(config.default_provider.as_deref(), Some("openai-codex"));
    assert_eq!(config.api_url.as_deref(), Some("https://api.tonsof.blue"));
    assert_eq!(config.api_key.as_deref(), Some("sk-test-codex-key"));
}

#[test]
async fn save_repairs_bare_config_filename_using_runtime_resolution() {
    let _env_guard = env_override_lock().await;
    let temp_home = std::env::temp_dir().join(format!("rain_test_home_{}", uuid::Uuid::new_v4()));
    let workspace_dir = temp_home.join("workspace");
    let resolved_config_path = temp_home.join(".R.A.I.N.").join("config.toml");

    let original_home = std::env::var("HOME").ok();
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("HOME", &temp_home);
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_WORKSPACE", &workspace_dir);
    }

    let mut config = Config::default();
    config.workspace_dir = workspace_dir;
    config.config_path = PathBuf::from("config.toml");
    config.default_temperature = 0.5;
    config.save().await.unwrap();

    assert!(resolved_config_path.exists());
    let saved = tokio::fs::read_to_string(&resolved_config_path)
        .await
        .unwrap();
    let parsed = parse_test_config(&saved);
    assert_eq!(parsed.default_temperature, 0.5);

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_WORKSPACE");
    }
    if let Some(home) = original_home {
        // SAFETY: single-threaded test/init context
        unsafe {
            std::env::set_var("HOME", home);
        }
    } else {
        // SAFETY: single-threaded test/init context
        unsafe {
            std::env::remove_var("HOME");
        }
    }
    let _ = tokio::fs::remove_dir_all(temp_home).await;
}

#[test]
async fn validate_ollama_cloud_model_requires_remote_api_url() {
    let _env_guard = env_override_lock().await;
    let config = Config {
        default_provider: Some("ollama".to_string()),
        default_model: Some("glm-5:cloud".to_string()),
        api_url: None,
        api_key: Some("ollama-key".to_string()),
        ..Config::default()
    };

    let error = config.validate().expect_err("expected validation to fail");
    assert!(error.to_string().contains(
        "default_model uses ':cloud' with provider 'ollama', but api_url is local or unset"
    ));
}

#[test]
async fn validate_ollama_cloud_model_accepts_remote_endpoint_and_env_key() {
    let _env_guard = env_override_lock().await;
    let config = Config {
        default_provider: Some("ollama".to_string()),
        default_model: Some("glm-5:cloud".to_string()),
        api_url: Some("https://ollama.com/api".to_string()),
        api_key: None,
        ..Config::default()
    };

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("OLLAMA_API_KEY", "ollama-env-key");
    }
    let result = config.validate();
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("OLLAMA_API_KEY");
    }

    assert!(result.is_ok(), "expected validation to pass: {result:?}");
}

#[test]
async fn validate_rejects_unknown_model_provider_wire_api() {
    let _env_guard = env_override_lock().await;
    let config = Config {
        default_provider: Some("sub2api".to_string()),
        model_providers: HashMap::from([(
            "sub2api".to_string(),
            ModelProviderConfig {
                name: Some("sub2api".to_string()),
                base_url: Some("https://api.tonsof.blue/v1".to_string()),
                wire_api: Some("ws".to_string()),
                requires_openai_auth: false,
                azure_openai_resource: None,
                azure_openai_deployment: None,
                azure_openai_api_version: None,
                api_path: None,
            },
        )]),
        ..Config::default()
    };

    let error = config.validate().expect_err("expected validation failure");
    assert!(
        error
            .to_string()
            .contains("wire_api must be one of: responses, chat_completions")
    );
}

#[test]
async fn env_override_model_fallback() {
    let _env_guard = env_override_lock().await;
    let mut config = Config::default();

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_MODEL");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("MODEL", "anthropic/claude-3.5-sonnet");
    }
    config.apply_env_overrides();
    assert_eq!(
        config.default_model.as_deref(),
        Some("anthropic/claude-3.5-sonnet")
    );

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("MODEL");
    }
}

#[test]
async fn env_override_workspace() {
    let _env_guard = env_override_lock().await;
    let mut config = Config::default();

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_WORKSPACE", "/custom/workspace");
    }
    config.apply_env_overrides();
    assert_eq!(config.workspace_dir, PathBuf::from("/custom/workspace"));

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_WORKSPACE");
    }
}

#[test]
async fn resolve_runtime_config_dirs_uses_env_workspace_first() {
    let _env_guard = env_override_lock().await;
    let default_config_dir = std::env::temp_dir().join(uuid::Uuid::new_v4().to_string());
    let default_workspace_dir = default_config_dir.join("workspace");
    let workspace_dir = default_config_dir.join("profile-a");

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_WORKSPACE", &workspace_dir);
    }
    let (config_dir, resolved_workspace_dir, source) =
        resolve_runtime_config_dirs(&default_config_dir, &default_workspace_dir)
            .await
            .unwrap();

    assert_eq!(source, ConfigResolutionSource::EnvWorkspace);
    assert_eq!(config_dir, workspace_dir);
    assert_eq!(resolved_workspace_dir, workspace_dir.join("workspace"));

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_WORKSPACE");
    }
    let _ = fs::remove_dir_all(default_config_dir).await;
}

#[test]
async fn resolve_runtime_config_dirs_uses_env_config_dir_first() {
    let _env_guard = env_override_lock().await;
    let default_config_dir = std::env::temp_dir().join(uuid::Uuid::new_v4().to_string());
    let default_workspace_dir = default_config_dir.join("workspace");
    let explicit_config_dir = default_config_dir.join("explicit-config");
    let marker_config_dir = default_config_dir.join("profiles").join("alpha");
    let state_path = default_config_dir.join(ACTIVE_WORKSPACE_STATE_FILE);

    fs::create_dir_all(&default_config_dir).await.unwrap();
    let state = ActiveWorkspaceState {
        config_dir: marker_config_dir.to_string_lossy().into_owned(),
    };
    fs::write(&state_path, toml::to_string(&state).unwrap())
        .await
        .unwrap();

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_CONFIG_DIR", &explicit_config_dir);
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_WORKSPACE");
    }

    let (config_dir, resolved_workspace_dir, source) =
        resolve_runtime_config_dirs(&default_config_dir, &default_workspace_dir)
            .await
            .unwrap();

    assert_eq!(source, ConfigResolutionSource::EnvConfigDir);
    assert_eq!(config_dir, explicit_config_dir);
    assert_eq!(
        resolved_workspace_dir,
        explicit_config_dir.join("workspace")
    );

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_CONFIG_DIR");
    }
    let _ = fs::remove_dir_all(default_config_dir).await;
}

#[test]
async fn resolve_runtime_config_dirs_uses_active_workspace_marker() {
    let _env_guard = env_override_lock().await;
    let default_config_dir = std::env::temp_dir().join(uuid::Uuid::new_v4().to_string());
    let default_workspace_dir = default_config_dir.join("workspace");
    let marker_config_dir = default_config_dir.join("profiles").join("alpha");
    let state_path = default_config_dir.join(ACTIVE_WORKSPACE_STATE_FILE);

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_WORKSPACE");
    }
    fs::create_dir_all(&default_config_dir).await.unwrap();
    let state = ActiveWorkspaceState {
        config_dir: marker_config_dir.to_string_lossy().into_owned(),
    };
    fs::write(&state_path, toml::to_string(&state).unwrap())
        .await
        .unwrap();

    let (config_dir, resolved_workspace_dir, source) =
        resolve_runtime_config_dirs(&default_config_dir, &default_workspace_dir)
            .await
            .unwrap();

    assert_eq!(source, ConfigResolutionSource::ActiveWorkspaceMarker);
    assert_eq!(config_dir, marker_config_dir);
    assert_eq!(resolved_workspace_dir, marker_config_dir.join("workspace"));

    let _ = fs::remove_dir_all(default_config_dir).await;
}

#[test]
async fn resolve_runtime_config_dirs_falls_back_to_default_layout() {
    let _env_guard = env_override_lock().await;
    let default_config_dir = std::env::temp_dir().join(uuid::Uuid::new_v4().to_string());
    let default_workspace_dir = default_config_dir.join("workspace");

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_WORKSPACE");
    }
    let (config_dir, resolved_workspace_dir, source) =
        resolve_runtime_config_dirs(&default_config_dir, &default_workspace_dir)
            .await
            .unwrap();

    assert_eq!(source, ConfigResolutionSource::DefaultConfigDir);
    assert_eq!(config_dir, default_config_dir);
    assert_eq!(resolved_workspace_dir, default_workspace_dir);

    let _ = fs::remove_dir_all(default_config_dir).await;
}

#[test]
async fn load_or_init_workspace_override_uses_workspace_root_for_config() {
    let _env_guard = env_override_lock().await;
    let temp_home = std::env::temp_dir().join(format!("rain_test_home_{}", uuid::Uuid::new_v4()));
    let workspace_dir = temp_home.join("profile-a");

    let original_home = std::env::var("HOME").ok();
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("HOME", &temp_home);
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_WORKSPACE", &workspace_dir);
    }

    let config = Box::pin(Config::load_or_init()).await.unwrap();

    assert_eq!(config.workspace_dir, workspace_dir.join("workspace"));
    assert_eq!(config.config_path, workspace_dir.join("config.toml"));
    assert!(workspace_dir.join("config.toml").exists());

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_WORKSPACE");
    }
    if let Some(home) = original_home {
        // SAFETY: single-threaded test/init context
        unsafe {
            std::env::set_var("HOME", home);
        }
    } else {
        // SAFETY: single-threaded test/init context
        unsafe {
            std::env::remove_var("HOME");
        }
    }
    let _ = fs::remove_dir_all(temp_home).await;
}

#[test]
async fn load_or_init_workspace_suffix_uses_legacy_config_layout() {
    let _env_guard = env_override_lock().await;
    let temp_home = std::env::temp_dir().join(format!("rain_test_home_{}", uuid::Uuid::new_v4()));
    let workspace_dir = temp_home.join("workspace");
    let legacy_config_path = temp_home.join(".R.A.I.N.").join("config.toml");

    let original_home = std::env::var("HOME").ok();
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("HOME", &temp_home);
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_WORKSPACE", &workspace_dir);
    }

    let config = Box::pin(Config::load_or_init()).await.unwrap();

    assert_eq!(config.workspace_dir, workspace_dir);
    assert_eq!(config.config_path, legacy_config_path);
    assert!(config.config_path.exists());

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_WORKSPACE");
    }
    if let Some(home) = original_home {
        // SAFETY: single-threaded test/init context
        unsafe {
            std::env::set_var("HOME", home);
        }
    } else {
        // SAFETY: single-threaded test/init context
        unsafe {
            std::env::remove_var("HOME");
        }
    }
    let _ = fs::remove_dir_all(temp_home).await;
}

#[test]
async fn load_or_init_workspace_override_keeps_existing_legacy_config() {
    let _env_guard = env_override_lock().await;
    let temp_home = std::env::temp_dir().join(format!("rain_test_home_{}", uuid::Uuid::new_v4()));
    let workspace_dir = temp_home.join("custom-workspace");
    let legacy_config_dir = temp_home.join(".R.A.I.N.");
    let legacy_config_path = legacy_config_dir.join("config.toml");

    fs::create_dir_all(&legacy_config_dir).await.unwrap();
    fs::write(
        &legacy_config_path,
        r#"default_temperature = 0.7
default_model = "legacy-model"
"#,
    )
    .await
    .unwrap();

    let original_home = std::env::var("HOME").ok();
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("HOME", &temp_home);
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_WORKSPACE", &workspace_dir);
    }

    let config = Box::pin(Config::load_or_init()).await.unwrap();

    assert_eq!(config.workspace_dir, workspace_dir);
    assert_eq!(config.config_path, legacy_config_path);
    assert_eq!(config.default_model.as_deref(), Some("legacy-model"));

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_WORKSPACE");
    }
    if let Some(home) = original_home {
        // SAFETY: single-threaded test/init context
        unsafe {
            std::env::set_var("HOME", home);
        }
    } else {
        // SAFETY: single-threaded test/init context
        unsafe {
            std::env::remove_var("HOME");
        }
    }
    let _ = fs::remove_dir_all(temp_home).await;
}

#[test]
async fn load_or_init_decrypts_feishu_channel_secrets() {
    let _env_guard = env_override_lock().await;
    let temp_home = std::env::temp_dir().join(format!("rain_test_home_{}", uuid::Uuid::new_v4()));
    let config_dir = temp_home.join(".R.A.I.N.");
    let config_path = config_dir.join("config.toml");

    fs::create_dir_all(&config_dir).await.unwrap();

    let original_home = std::env::var("HOME").ok();
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("HOME", &temp_home);
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_CONFIG_DIR");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_WORKSPACE");
    }

    let mut config = Config::default();
    config.config_path = config_path.clone();
    config.workspace_dir = config_dir.join("workspace");
    config.secrets.encrypt = true;
    config.channels_config.feishu = Some(FeishuConfig {
        app_id: "cli_feishu_123".into(),
        app_secret: "feishu-secret".into(),
        encrypt_key: Some("feishu-encrypt".into()),
        verification_token: Some("feishu-verify".into()),
        allowed_users: vec!["*".into()],
        receive_mode: LarkReceiveMode::Websocket,
        port: None,
        proxy_url: None,
    });
    config.save().await.unwrap();

    let loaded = Box::pin(Config::load_or_init()).await.unwrap();
    let feishu = loaded.channels_config.feishu.as_ref().unwrap();
    assert_eq!(feishu.app_secret, "feishu-secret");
    assert_eq!(feishu.encrypt_key.as_deref(), Some("feishu-encrypt"));
    assert_eq!(feishu.verification_token.as_deref(), Some("feishu-verify"));

    if let Some(home) = original_home {
        // SAFETY: single-threaded test/init context
        unsafe {
            std::env::set_var("HOME", home);
        }
    } else {
        // SAFETY: single-threaded test/init context
        unsafe {
            std::env::remove_var("HOME");
        }
    }
    let _ = fs::remove_dir_all(temp_home).await;
}

#[test]
async fn load_or_init_uses_persisted_active_workspace_marker() {
    let _env_guard = env_override_lock().await;
    let temp_home = std::env::temp_dir().join(format!("rain_test_home_{}", uuid::Uuid::new_v4()));
    let temp_default_dir = temp_home.join(".R.A.I.N.");
    let custom_config_dir = temp_home.join("profiles").join("agent-alpha");

    fs::create_dir_all(&custom_config_dir).await.unwrap();
    fs::write(
        custom_config_dir.join("config.toml"),
        "default_temperature = 0.7\ndefault_model = \"persisted-profile\"\n",
    )
    .await
    .unwrap();

    // Write the marker using the explicit default dir (no HOME manipulation
    // needed for the persist call itself).
    persist_active_workspace_config_dir_in(&custom_config_dir, &temp_default_dir)
        .await
        .unwrap();

    // Config::load_or_init still reads HOME to find the marker, so we
    // must override HOME here. The persist above already wrote to the
    // correct temp location, so no stale marker can leak.
    let original_home = std::env::var("HOME").ok();
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("HOME", &temp_home);
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_WORKSPACE");
    }

    let config = Box::pin(Config::load_or_init()).await.unwrap();

    assert_eq!(config.config_path, custom_config_dir.join("config.toml"));
    assert_eq!(config.workspace_dir, custom_config_dir.join("workspace"));
    assert_eq!(config.default_model.as_deref(), Some("persisted-profile"));

    if let Some(home) = original_home {
        // SAFETY: single-threaded test/init context
        unsafe {
            std::env::set_var("HOME", home);
        }
    } else {
        // SAFETY: single-threaded test/init context
        unsafe {
            std::env::remove_var("HOME");
        }
    }
    let _ = fs::remove_dir_all(temp_home).await;
}

#[test]
async fn load_or_init_env_workspace_override_takes_priority_over_marker() {
    let _env_guard = env_override_lock().await;
    let temp_home = std::env::temp_dir().join(format!("rain_test_home_{}", uuid::Uuid::new_v4()));
    let temp_default_dir = temp_home.join(".R.A.I.N.");
    let marker_config_dir = temp_home.join("profiles").join("persisted-profile");
    let env_workspace_dir = temp_home.join("env-workspace");

    fs::create_dir_all(&marker_config_dir).await.unwrap();
    fs::write(
        marker_config_dir.join("config.toml"),
        "default_temperature = 0.7\ndefault_model = \"marker-model\"\n",
    )
    .await
    .unwrap();

    // Write marker via explicit default dir, then set HOME for load_or_init.
    persist_active_workspace_config_dir_in(&marker_config_dir, &temp_default_dir)
        .await
        .unwrap();

    let original_home = std::env::var("HOME").ok();
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("HOME", &temp_home);
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_WORKSPACE", &env_workspace_dir);
    }

    let config = Box::pin(Config::load_or_init()).await.unwrap();

    assert_eq!(config.workspace_dir, env_workspace_dir.join("workspace"));
    assert_eq!(config.config_path, env_workspace_dir.join("config.toml"));

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_WORKSPACE");
    }
    if let Some(home) = original_home {
        // SAFETY: single-threaded test/init context
        unsafe {
            std::env::set_var("HOME", home);
        }
    } else {
        // SAFETY: single-threaded test/init context
        unsafe {
            std::env::remove_var("HOME");
        }
    }
    let _ = fs::remove_dir_all(temp_home).await;
}

#[test]
async fn persist_active_workspace_marker_is_cleared_for_default_config_dir() {
    let temp_home = std::env::temp_dir().join(format!("rain_test_home_{}", uuid::Uuid::new_v4()));
    let default_config_dir = temp_home.join(".R.A.I.N.");
    let custom_config_dir = temp_home.join("profiles").join("custom-profile");
    let marker_path = default_config_dir.join(ACTIVE_WORKSPACE_STATE_FILE);

    // Use the _in variant directly -- no HOME manipulation needed since
    // this test only exercises persist/clear logic, not Config::load_or_init.
    persist_active_workspace_config_dir_in(&custom_config_dir, &default_config_dir)
        .await
        .unwrap();
    assert!(marker_path.exists());

    persist_active_workspace_config_dir_in(&default_config_dir, &default_config_dir)
        .await
        .unwrap();
    assert!(!marker_path.exists());

    let _ = fs::remove_dir_all(temp_home).await;
}

#[test]
#[allow(clippy::large_futures)]
async fn load_or_init_logs_existing_config_as_initialized() {
    let _env_guard = env_override_lock().await;
    let temp_home = std::env::temp_dir().join(format!("rain_test_home_{}", uuid::Uuid::new_v4()));
    let workspace_dir = temp_home.join("profile-a");
    let config_path = workspace_dir.join("config.toml");

    fs::create_dir_all(&workspace_dir).await.unwrap();
    fs::write(
        &config_path,
        r#"default_temperature = 0.7
default_model = "persisted-profile"
"#,
    )
    .await
    .unwrap();

    let original_home = std::env::var("HOME").ok();
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("HOME", &temp_home);
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_WORKSPACE", &workspace_dir);
    }

    let capture = SharedLogBuffer::default();
    let subscriber = tracing_subscriber::fmt()
        .with_ansi(false)
        .without_time()
        .with_target(false)
        .with_writer(capture.clone())
        .finish();
    let dispatch = tracing::Dispatch::new(subscriber);
    let guard = tracing::dispatcher::set_default(&dispatch);

    let config = Box::pin(Config::load_or_init()).await.unwrap();

    drop(guard);
    let logs = capture.captured();

    assert_eq!(config.workspace_dir, workspace_dir.join("workspace"));
    assert_eq!(config.config_path, config_path);
    assert_eq!(config.default_model.as_deref(), Some("persisted-profile"));
    assert!(logs.contains("Config loaded"), "{logs}");
    assert!(logs.contains("initialized=true"), "{logs}");
    assert!(!logs.contains("initialized=false"), "{logs}");

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_WORKSPACE");
    }
    if let Some(home) = original_home {
        // SAFETY: single-threaded test/init context
        unsafe {
            std::env::set_var("HOME", home);
        }
    } else {
        // SAFETY: single-threaded test/init context
        unsafe {
            std::env::remove_var("HOME");
        }
    }
    let _ = fs::remove_dir_all(temp_home).await;
}

#[test]
async fn apply_env_overrides_warns_for_reserved_conversational_ai_config() {
    let capture = SharedLogBuffer::default();
    let subscriber = tracing_subscriber::fmt()
        .with_ansi(false)
        .without_time()
        .with_target(false)
        .with_writer(capture.clone())
        .finish();
    let dispatch = tracing::Dispatch::new(subscriber);
    let guard = tracing::dispatcher::set_default(&dispatch);

    let mut config = Config::default();
    config.conversational_ai.enabled = true;
    config.apply_env_overrides();

    drop(guard);
    let logs = capture.captured();
    assert!(
        logs.contains("conversational_ai.enabled = true"),
        "expected reserved-config warning, got: {logs}"
    );
}

#[test]
async fn env_override_empty_values_ignored() {
    let _env_guard = env_override_lock().await;
    let mut config = Config::default();
    let original_provider = config.default_provider.clone();

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_PROVIDER", "");
    }
    config.apply_env_overrides();
    assert_eq!(config.default_provider, original_provider);

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_PROVIDER");
    }
}

#[test]
async fn env_override_gateway_port() {
    let _env_guard = env_override_lock().await;
    let mut config = Config::default();
    assert_eq!(config.gateway.port, 42617);

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_GATEWAY_PORT", "8080");
    }
    config.apply_env_overrides();
    assert_eq!(config.gateway.port, 8080);

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_GATEWAY_PORT");
    }
}

#[test]
async fn env_override_port_fallback() {
    let _env_guard = env_override_lock().await;
    let mut config = Config::default();

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_GATEWAY_PORT");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("PORT", "9000");
    }
    config.apply_env_overrides();
    assert_eq!(config.gateway.port, 9000);

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("PORT");
    }
}

#[test]
async fn env_override_gateway_host() {
    let _env_guard = env_override_lock().await;
    let mut config = Config::default();
    assert_eq!(config.gateway.host, "127.0.0.1");

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_GATEWAY_HOST", "0.0.0.0");
    }
    config.apply_env_overrides();
    assert_eq!(config.gateway.host, "0.0.0.0");

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_GATEWAY_HOST");
    }
}

#[test]
async fn env_override_host_fallback() {
    let _env_guard = env_override_lock().await;
    let mut config = Config::default();

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_GATEWAY_HOST");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("HOST", "0.0.0.0");
    }
    config.apply_env_overrides();
    assert_eq!(config.gateway.host, "0.0.0.0");

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("HOST");
    }
}

#[test]
async fn env_override_temperature() {
    let _env_guard = env_override_lock().await;
    let mut config = Config::default();

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_TEMPERATURE", "0.5");
    }
    config.apply_env_overrides();
    assert!((config.default_temperature - 0.5).abs() < f64::EPSILON);

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_TEMPERATURE");
    }
}

#[test]
async fn env_override_temperature_out_of_range_ignored() {
    let _env_guard = env_override_lock().await;
    // Clean up any leftover env vars from other tests
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_TEMPERATURE");
    }

    let mut config = Config::default();
    let original_temp = config.default_temperature;

    // Temperature > 2.0 should be ignored
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_TEMPERATURE", "3.0");
    }
    config.apply_env_overrides();
    assert!(
        (config.default_temperature - original_temp).abs() < f64::EPSILON,
        "Temperature 3.0 should be ignored (out of range)"
    );

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_TEMPERATURE");
    }
}

#[test]
async fn env_override_reasoning_enabled() {
    let _env_guard = env_override_lock().await;
    let mut config = Config::default();
    assert_eq!(config.runtime.reasoning_enabled, None);

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_REASONING_ENABLED", "false");
    }
    config.apply_env_overrides();
    assert_eq!(config.runtime.reasoning_enabled, Some(false));

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_REASONING_ENABLED", "true");
    }
    config.apply_env_overrides();
    assert_eq!(config.runtime.reasoning_enabled, Some(true));

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_REASONING_ENABLED");
    }
}

#[test]
async fn env_override_reasoning_invalid_value_ignored() {
    let _env_guard = env_override_lock().await;
    let mut config = Config::default();
    config.runtime.reasoning_enabled = Some(false);

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_REASONING_ENABLED", "maybe");
    }
    config.apply_env_overrides();
    assert_eq!(config.runtime.reasoning_enabled, Some(false));

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_REASONING_ENABLED");
    }
}

#[test]
async fn env_override_reasoning_effort() {
    let _env_guard = env_override_lock().await;
    let mut config = Config::default();
    assert_eq!(config.runtime.reasoning_effort, None);

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_REASONING_EFFORT", "HIGH");
    }
    config.apply_env_overrides();
    assert_eq!(config.runtime.reasoning_effort.as_deref(), Some("high"));

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_REASONING_EFFORT");
    }
}

#[test]
async fn env_override_reasoning_effort_legacy_codex_env() {
    let _env_guard = env_override_lock().await;
    let mut config = Config::default();

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_CODEX_REASONING_EFFORT", "minimal");
    }
    config.apply_env_overrides();
    assert_eq!(config.runtime.reasoning_effort.as_deref(), Some("minimal"));

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_CODEX_REASONING_EFFORT");
    }
}

#[test]
async fn env_override_invalid_port_ignored() {
    let _env_guard = env_override_lock().await;
    let mut config = Config::default();
    let original_port = config.gateway.port;

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("PORT", "not_a_number");
    }
    config.apply_env_overrides();
    assert_eq!(config.gateway.port, original_port);

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("PORT");
    }
}

#[test]
async fn env_override_web_search_config() {
    let _env_guard = env_override_lock().await;
    let mut config = Config::default();

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("WEB_SEARCH_ENABLED", "false");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("WEB_SEARCH_PROVIDER", "brave");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("WEB_SEARCH_MAX_RESULTS", "7");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("WEB_SEARCH_TIMEOUT_SECS", "20");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("BRAVE_API_KEY", "brave-test-key");
    }

    config.apply_env_overrides();

    assert!(!config.web_search.enabled);
    assert_eq!(config.web_search.provider, "brave");
    assert_eq!(config.web_search.max_results, 7);
    assert_eq!(config.web_search.timeout_secs, 20);
    assert_eq!(
        config.web_search.brave_api_key.as_deref(),
        Some("brave-test-key")
    );

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("WEB_SEARCH_ENABLED");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("WEB_SEARCH_PROVIDER");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("WEB_SEARCH_MAX_RESULTS");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("WEB_SEARCH_TIMEOUT_SECS");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("BRAVE_API_KEY");
    }
}

#[test]
async fn env_override_web_search_invalid_values_ignored() {
    let _env_guard = env_override_lock().await;
    let mut config = Config::default();
    let original_max_results = config.web_search.max_results;
    let original_timeout = config.web_search.timeout_secs;

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("WEB_SEARCH_MAX_RESULTS", "99");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("WEB_SEARCH_TIMEOUT_SECS", "0");
    }

    config.apply_env_overrides();

    assert_eq!(config.web_search.max_results, original_max_results);
    assert_eq!(config.web_search.timeout_secs, original_timeout);

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("WEB_SEARCH_MAX_RESULTS");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("WEB_SEARCH_TIMEOUT_SECS");
    }
}

#[test]
async fn env_override_storage_provider_config() {
    let _env_guard = env_override_lock().await;
    let mut config = Config::default();

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_STORAGE_PROVIDER", "postgres");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_STORAGE_DB_URL", "postgres://example/db");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_STORAGE_CONNECT_TIMEOUT_SECS", "15");
    }

    config.apply_env_overrides();

    assert_eq!(config.storage.provider.config.provider, "postgres");
    assert_eq!(
        config.storage.provider.config.db_url.as_deref(),
        Some("postgres://example/db")
    );
    assert_eq!(
        config.storage.provider.config.connect_timeout_secs,
        Some(15)
    );

    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_STORAGE_PROVIDER");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_STORAGE_DB_URL");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::remove_var("rain_STORAGE_CONNECT_TIMEOUT_SECS");
    }
}

#[test]
async fn proxy_config_scope_services_requires_entries_when_enabled() {
    let proxy = ProxyConfig {
        enabled: true,
        http_proxy: Some("http://127.0.0.1:7890".into()),
        https_proxy: None,
        all_proxy: None,
        no_proxy: Vec::new(),
        scope: ProxyScope::Services,
        services: Vec::new(),
    };

    let error = proxy.validate().unwrap_err().to_string();
    assert!(error.contains("proxy.scope='services'"));
}

#[test]
async fn env_override_proxy_scope_services() {
    let _env_guard = env_override_lock().await;
    clear_proxy_env_test_vars();

    let mut config = Config::default();
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_PROXY_ENABLED", "true");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_HTTP_PROXY", "http://127.0.0.1:7890");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_PROXY_SERVICES", "provider.openai, tool.http_request");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_PROXY_SCOPE", "services");
    }

    config.apply_env_overrides();

    assert!(config.proxy.enabled);
    assert_eq!(config.proxy.scope, ProxyScope::Services);
    assert_eq!(
        config.proxy.http_proxy.as_deref(),
        Some("http://127.0.0.1:7890")
    );
    assert!(config.proxy.should_apply_to_service("provider.openai"));
    assert!(config.proxy.should_apply_to_service("tool.http_request"));
    assert!(!config.proxy.should_apply_to_service("provider.anthropic"));

    clear_proxy_env_test_vars();
}

#[test]
async fn env_override_proxy_scope_environment_applies_process_env() {
    let _env_guard = env_override_lock().await;
    clear_proxy_env_test_vars();

    let mut config = Config::default();
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_PROXY_ENABLED", "true");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_PROXY_SCOPE", "environment");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_HTTP_PROXY", "http://127.0.0.1:7890");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_HTTPS_PROXY", "http://127.0.0.1:7891");
    }
    // SAFETY: single-threaded test/init context
    unsafe {
        std::env::set_var("rain_NO_PROXY", "localhost,127.0.0.1");
    }

    config.apply_env_overrides();

    assert_eq!(config.proxy.scope, ProxyScope::Environment);
    assert_eq!(
        std::env::var("HTTP_PROXY").ok().as_deref(),
        Some("http://127.0.0.1:7890")
    );
    assert_eq!(
        std::env::var("HTTPS_PROXY").ok().as_deref(),
        Some("http://127.0.0.1:7891")
    );
    assert!(
        std::env::var("NO_PROXY")
            .ok()
            .is_some_and(|value| value.contains("localhost"))
    );

    clear_proxy_env_test_vars();
}

#[test]
async fn google_workspace_allowed_operations_require_methods() {
    let mut config = Config::default();
    config.google_workspace.allowed_operations = vec![GoogleWorkspaceAllowedOperation {
        service: "gmail".into(),
        resource: "users".into(),
        sub_resource: Some("drafts".into()),
        methods: Vec::new(),
    }];

    let err = config.validate().unwrap_err().to_string();
    assert!(err.contains("google_workspace.allowed_operations[0].methods"));
}

#[test]
async fn google_workspace_allowed_operations_reject_duplicate_service_resource_sub_resource_entries()
 {
    let mut config = Config::default();
    config.google_workspace.allowed_operations = vec![
        GoogleWorkspaceAllowedOperation {
            service: "gmail".into(),
            resource: "users".into(),
            sub_resource: Some("drafts".into()),
            methods: vec!["create".into()],
        },
        GoogleWorkspaceAllowedOperation {
            service: "gmail".into(),
            resource: "users".into(),
            sub_resource: Some("drafts".into()),
            methods: vec!["update".into()],
        },
    ];

    let err = config.validate().unwrap_err().to_string();
    assert!(err.contains("duplicate service/resource/sub_resource entry"));
}

#[test]
async fn google_workspace_allowed_operations_allow_same_resource_different_sub_resource() {
    let mut config = Config::default();
    config.google_workspace.allowed_operations = vec![
        GoogleWorkspaceAllowedOperation {
            service: "gmail".into(),
            resource: "users".into(),
            sub_resource: Some("messages".into()),
            methods: vec!["list".into(), "get".into()],
        },
        GoogleWorkspaceAllowedOperation {
            service: "gmail".into(),
            resource: "users".into(),
            sub_resource: Some("drafts".into()),
            methods: vec!["create".into(), "update".into()],
        },
    ];

    assert!(config.validate().is_ok());
}

#[test]
async fn google_workspace_allowed_operations_reject_duplicate_methods_within_entry() {
    let mut config = Config::default();
    config.google_workspace.allowed_operations = vec![GoogleWorkspaceAllowedOperation {
        service: "gmail".into(),
        resource: "users".into(),
        sub_resource: Some("drafts".into()),
        methods: vec!["create".into(), "create".into()],
    }];

    let err = config.validate().unwrap_err().to_string();
    assert!(
        err.contains("duplicate entry"),
        "expected duplicate entry error, got: {err}"
    );
}

#[test]
async fn google_workspace_allowed_operations_accept_valid_entries() {
    let mut config = Config::default();
    config.google_workspace.allowed_operations = vec![
        GoogleWorkspaceAllowedOperation {
            service: "gmail".into(),
            resource: "users".into(),
            sub_resource: Some("messages".into()),
            methods: vec!["list".into(), "get".into()],
        },
        GoogleWorkspaceAllowedOperation {
            service: "drive".into(),
            resource: "files".into(),
            sub_resource: None,
            methods: vec!["list".into(), "get".into()],
        },
    ];

    assert!(config.validate().is_ok());
}

#[test]
async fn google_workspace_allowed_operations_reject_invalid_sub_resource_characters() {
    let mut config = Config::default();
    config.google_workspace.allowed_operations = vec![GoogleWorkspaceAllowedOperation {
        service: "gmail".into(),
        resource: "users".into(),
        sub_resource: Some("bad resource!".into()),
        methods: vec!["list".into()],
    }];

    let err = config.validate().unwrap_err().to_string();
    assert!(err.contains("sub_resource contains invalid characters"));
}

fn runtime_proxy_cache_contains(cache_key: &str) -> bool {
    current_runtime_proxy_state().is_some_and(|state| state.contains_cached_client(cache_key))
}

#[test]
async fn runtime_proxy_client_cache_reuses_default_profile_key() {
    let state = RuntimeProxyStateHandle::default();
    let service_key = format!(
        "provider.cache_test.{}",
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .expect("system clock should be after unix epoch")
            .as_nanos()
    );
    let cache_key = runtime_proxy_cache_key(&service_key, None, None);

    with_runtime_proxy_state(state, async {
        clear_runtime_proxy_client_cache();
        assert!(!runtime_proxy_cache_contains(&cache_key));

        let _ = build_runtime_proxy_client(&service_key);
        assert!(runtime_proxy_cache_contains(&cache_key));

        let _ = build_runtime_proxy_client(&service_key);
        assert!(runtime_proxy_cache_contains(&cache_key));
    })
    .await;
}

#[test]
async fn set_runtime_proxy_config_clears_runtime_proxy_client_cache() {
    let state = RuntimeProxyStateHandle::default();
    let service_key = format!(
        "provider.cache_timeout_test.{}",
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .expect("system clock should be after unix epoch")
            .as_nanos()
    );
    let cache_key = runtime_proxy_cache_key(&service_key, Some(30), Some(5));

    with_runtime_proxy_state(state, async {
        clear_runtime_proxy_client_cache();
        let _ = build_runtime_proxy_client_with_timeouts(&service_key, 30, 5);
        assert!(runtime_proxy_cache_contains(&cache_key));

        set_runtime_proxy_config(ProxyConfig::default());
        assert!(!runtime_proxy_cache_contains(&cache_key));
    })
    .await;
}

#[test]
async fn gateway_config_default_values() {
    let g = GatewayConfig::default();
    assert_eq!(g.port, 42617);
    assert_eq!(g.host, "127.0.0.1");
    assert!(g.require_pairing);
    assert!(!g.allow_public_bind);
    assert!(g.paired_tokens.is_empty());
    assert!(!g.trust_forwarded_headers);
    assert_eq!(g.rate_limit_max_keys, 10_000);
    assert_eq!(g.idempotency_max_keys, 10_000);
}

// ── Peripherals config ───────────────────────────────────────

#[test]
async fn peripherals_config_default_disabled() {
    let p = PeripheralsConfig::default();
    assert!(!p.enabled);
    assert!(p.boards.is_empty());
}

#[test]
async fn peripheral_board_config_defaults() {
    let b = PeripheralBoardConfig::default();
    assert!(b.board.is_empty());
    assert_eq!(b.transport, "serial");
    assert!(b.path.is_none());
    assert_eq!(b.baud, 115_200);
}

#[test]
async fn peripherals_config_toml_roundtrip() {
    let p = PeripheralsConfig {
        enabled: true,
        boards: vec![PeripheralBoardConfig {
            board: "nucleo-f401re".into(),
            transport: "serial".into(),
            path: Some("/dev/ttyACM0".into()),
            baud: 115_200,
        }],
        datasheet_dir: None,
    };
    let toml_str = toml::to_string(&p).unwrap();
    let parsed: PeripheralsConfig = toml::from_str(&toml_str).unwrap();
    assert!(parsed.enabled);
    assert_eq!(parsed.boards.len(), 1);
    assert_eq!(parsed.boards[0].board, "nucleo-f401re");
    assert_eq!(parsed.boards[0].path.as_deref(), Some("/dev/ttyACM0"));
}

#[test]
async fn lark_config_serde() {
    let lc = LarkConfig {
        app_id: "cli_123456".into(),
        app_secret: "secret_abc".into(),
        encrypt_key: Some("encrypt_key".into()),
        verification_token: Some("verify_token".into()),
        allowed_users: vec!["user_123".into(), "user_456".into()],
        mention_only: false,
        use_feishu: true,
        receive_mode: LarkReceiveMode::Websocket,
        port: None,
        proxy_url: None,
    };
    let json = serde_json::to_string(&lc).unwrap();
    let parsed: LarkConfig = serde_json::from_str(&json).unwrap();
    assert_eq!(parsed.app_id, "cli_123456");
    assert_eq!(parsed.app_secret, "secret_abc");
    assert_eq!(parsed.encrypt_key.as_deref(), Some("encrypt_key"));
    assert_eq!(parsed.verification_token.as_deref(), Some("verify_token"));
    assert_eq!(parsed.allowed_users.len(), 2);
    assert!(parsed.use_feishu);
}

#[test]
async fn lark_config_toml_roundtrip() {
    let lc = LarkConfig {
        app_id: "cli_123456".into(),
        app_secret: "secret_abc".into(),
        encrypt_key: Some("encrypt_key".into()),
        verification_token: Some("verify_token".into()),
        allowed_users: vec!["*".into()],
        mention_only: false,
        use_feishu: false,
        receive_mode: LarkReceiveMode::Webhook,
        port: Some(9898),
        proxy_url: None,
    };
    let toml_str = toml::to_string(&lc).unwrap();
    let parsed: LarkConfig = toml::from_str(&toml_str).unwrap();
    assert_eq!(parsed.app_id, "cli_123456");
    assert_eq!(parsed.app_secret, "secret_abc");
    assert!(!parsed.use_feishu);
}

#[test]
async fn lark_config_deserializes_without_optional_fields() {
    let json = r#"{"app_id":"cli_123","app_secret":"secret"}"#;
    let parsed: LarkConfig = serde_json::from_str(json).unwrap();
    assert!(parsed.encrypt_key.is_none());
    assert!(parsed.verification_token.is_none());
    assert!(parsed.allowed_users.is_empty());
    assert!(!parsed.mention_only);
    assert!(!parsed.use_feishu);
}

#[test]
async fn lark_config_defaults_to_lark_endpoint() {
    let json = r#"{"app_id":"cli_123","app_secret":"secret"}"#;
    let parsed: LarkConfig = serde_json::from_str(json).unwrap();
    assert!(
        !parsed.use_feishu,
        "use_feishu should default to false (Lark)"
    );
}

#[test]
async fn lark_config_with_wildcard_allowed_users() {
    let json = r#"{"app_id":"cli_123","app_secret":"secret","allowed_users":["*"]}"#;
    let parsed: LarkConfig = serde_json::from_str(json).unwrap();
    assert_eq!(parsed.allowed_users, vec!["*"]);
}

#[test]
async fn feishu_config_serde() {
    let fc = FeishuConfig {
        app_id: "cli_feishu_123".into(),
        app_secret: "secret_abc".into(),
        encrypt_key: Some("encrypt_key".into()),
        verification_token: Some("verify_token".into()),
        allowed_users: vec!["user_123".into(), "user_456".into()],
        receive_mode: LarkReceiveMode::Websocket,
        port: None,
        proxy_url: None,
    };
    let json = serde_json::to_string(&fc).unwrap();
    let parsed: FeishuConfig = serde_json::from_str(&json).unwrap();
    assert_eq!(parsed.app_id, "cli_feishu_123");
    assert_eq!(parsed.app_secret, "secret_abc");
    assert_eq!(parsed.encrypt_key.as_deref(), Some("encrypt_key"));
    assert_eq!(parsed.verification_token.as_deref(), Some("verify_token"));
    assert_eq!(parsed.allowed_users.len(), 2);
}

#[test]
async fn feishu_config_toml_roundtrip() {
    let fc = FeishuConfig {
        app_id: "cli_feishu_123".into(),
        app_secret: "secret_abc".into(),
        encrypt_key: Some("encrypt_key".into()),
        verification_token: Some("verify_token".into()),
        allowed_users: vec!["*".into()],
        receive_mode: LarkReceiveMode::Webhook,
        port: Some(9898),
        proxy_url: None,
    };
    let toml_str = toml::to_string(&fc).unwrap();
    let parsed: FeishuConfig = toml::from_str(&toml_str).unwrap();
    assert_eq!(parsed.app_id, "cli_feishu_123");
    assert_eq!(parsed.app_secret, "secret_abc");
    assert_eq!(parsed.receive_mode, LarkReceiveMode::Webhook);
    assert_eq!(parsed.port, Some(9898));
}

#[test]
async fn feishu_config_deserializes_without_optional_fields() {
    let json = r#"{"app_id":"cli_123","app_secret":"secret"}"#;
    let parsed: FeishuConfig = serde_json::from_str(json).unwrap();
    assert!(parsed.encrypt_key.is_none());
    assert!(parsed.verification_token.is_none());
    assert!(parsed.allowed_users.is_empty());
    assert_eq!(parsed.receive_mode, LarkReceiveMode::Websocket);
    assert!(parsed.port.is_none());
}

#[test]
async fn nextcloud_talk_config_serde() {
    let nc = NextcloudTalkConfig {
        base_url: "https://cloud.example.com".into(),
        app_token: "app-token".into(),
        webhook_secret: Some("webhook-secret".into()),
        allowed_users: vec!["user_a".into(), "*".into()],
        proxy_url: None,
    };

    let json = serde_json::to_string(&nc).unwrap();
    let parsed: NextcloudTalkConfig = serde_json::from_str(&json).unwrap();
    assert_eq!(parsed.base_url, "https://cloud.example.com");
    assert_eq!(parsed.app_token, "app-token");
    assert_eq!(parsed.webhook_secret.as_deref(), Some("webhook-secret"));
    assert_eq!(parsed.allowed_users, vec!["user_a", "*"]);
}

#[test]
async fn nextcloud_talk_config_defaults_optional_fields() {
    let json = r#"{"base_url":"https://cloud.example.com","app_token":"app-token"}"#;
    let parsed: NextcloudTalkConfig = serde_json::from_str(json).unwrap();
    assert!(parsed.webhook_secret.is_none());
    assert!(parsed.allowed_users.is_empty());
}

// ── Config file permission hardening (Unix only) ───────────────

#[cfg(unix)]
#[test]
async fn new_config_file_has_restricted_permissions() {
    let tmp = tempfile::TempDir::new().unwrap();
    let config_path = tmp.path().join("config.toml");

    // Create a config and save it
    let mut config = Config::default();
    config.config_path = config_path.clone();
    config.save().await.unwrap();

    let meta = fs::metadata(&config_path).await.unwrap();
    let mode = meta.permissions().mode() & 0o777;
    assert_eq!(
        mode, 0o600,
        "New config file should be owner-only (0600), got {mode:o}"
    );
}

#[cfg(unix)]
#[test]
async fn save_restricts_existing_world_readable_config_to_owner_only() {
    let tmp = tempfile::TempDir::new().unwrap();
    let config_path = tmp.path().join("config.toml");

    let mut config = Config::default();
    config.config_path = config_path.clone();
    config.save().await.unwrap();

    // Simulate the regression state observed in issue #1345.
    std::fs::set_permissions(&config_path, std::fs::Permissions::from_mode(0o644)).unwrap();
    let loose_mode = std::fs::metadata(&config_path)
        .unwrap()
        .permissions()
        .mode()
        & 0o777;
    assert_eq!(
        loose_mode, 0o644,
        "test setup requires world-readable config"
    );

    config.default_temperature = 0.6;
    config.save().await.unwrap();

    let hardened_mode = std::fs::metadata(&config_path)
        .unwrap()
        .permissions()
        .mode()
        & 0o777;
    assert_eq!(
        hardened_mode, 0o600,
        "Saving config should restore owner-only permissions (0600)"
    );
}

#[cfg(unix)]
#[test]
async fn world_readable_config_is_detectable() {
    use std::os::unix::fs::PermissionsExt;

    let tmp = tempfile::TempDir::new().unwrap();
    let config_path = tmp.path().join("config.toml");

    // Create a config file with intentionally loose permissions
    std::fs::write(&config_path, "# test config").unwrap();
    std::fs::set_permissions(&config_path, std::fs::Permissions::from_mode(0o644)).unwrap();

    let meta = std::fs::metadata(&config_path).unwrap();
    let mode = meta.permissions().mode();
    assert!(
        mode & 0o004 != 0,
        "Test setup: file should be world-readable (mode {mode:o})"
    );
}

#[test]
async fn transcription_config_defaults() {
    let tc = TranscriptionConfig::default();
    assert!(!tc.enabled);
    assert!(tc.api_url.contains("groq.com"));
    assert_eq!(tc.model, "whisper-large-v3-turbo");
    assert!(tc.language.is_none());
    assert_eq!(tc.max_duration_secs, 120);
}

#[test]
async fn config_roundtrip_with_transcription() {
    let mut config = Config::default();
    config.transcription.enabled = true;
    config.transcription.language = Some("en".into());

    let toml_str = toml::to_string_pretty(&config).unwrap();
    let parsed = parse_test_config(&toml_str);

    assert!(parsed.transcription.enabled);
    assert_eq!(parsed.transcription.language.as_deref(), Some("en"));
    assert_eq!(parsed.transcription.model, "whisper-large-v3-turbo");
}

#[test]
async fn config_without_transcription_uses_defaults() {
    let toml_str = r#"
        default_provider = "openrouter"
        default_model = "test-model"
        default_temperature = 0.7
    "#;
    let parsed = parse_test_config(toml_str);
    assert!(!parsed.transcription.enabled);
    assert_eq!(parsed.transcription.max_duration_secs, 120);
}

#[test]
async fn security_defaults_are_backward_compatible() {
    let parsed = parse_test_config(
        r#"
default_provider = "openrouter"
default_model = "anthropic/claude-sonnet-4.6"
default_temperature = 0.7
"#,
    );

    assert!(!parsed.security.otp.enabled);
    assert_eq!(parsed.security.otp.method, OtpMethod::Totp);
    assert!(!parsed.security.estop.enabled);
    assert!(parsed.security.estop.require_otp_to_resume);
}

#[test]
async fn security_toml_parses_otp_and_estop_sections() {
    let parsed = parse_test_config(
        r#"
default_provider = "openrouter"
default_model = "anthropic/claude-sonnet-4.6"
default_temperature = 0.7

[security.otp]
enabled = true
method = "totp"
token_ttl_secs = 30
cache_valid_secs = 120
gated_actions = ["shell", "browser_open"]
gated_domains = ["*.chase.com", "accounts.google.com"]
gated_domain_categories = ["banking"]

[security.estop]
enabled = true
state_file = "~/.R.A.I.N./estop-state.json"
require_otp_to_resume = true
"#,
    );

    assert!(parsed.security.otp.enabled);
    assert!(parsed.security.estop.enabled);
    assert_eq!(parsed.security.otp.gated_actions.len(), 2);
    assert_eq!(parsed.security.otp.gated_domains.len(), 2);
    parsed.validate().unwrap();
}

#[test]
async fn security_validation_rejects_invalid_domain_glob() {
    let mut config = Config::default();
    config.security.otp.gated_domains = vec!["bad domain.com".into()];

    let err = config.validate().expect_err("expected invalid domain glob");
    assert!(err.to_string().contains("gated_domains"));
}

#[test]
async fn validate_accepts_local_whisper_as_transcription_default_provider() {
    let mut config = Config::default();
    config.transcription.default_provider = "local_whisper".to_string();

    config
        .validate()
        .expect("local_whisper must be accepted by the transcription.default_provider allowlist");
}

#[test]
async fn validate_rejects_unknown_transcription_default_provider() {
    let mut config = Config::default();
    config.transcription.default_provider = "unknown_stt".to_string();

    let err = config
        .validate()
        .expect_err("expected validation to reject unknown transcription provider");
    assert!(
        err.to_string().contains("transcription.default_provider"),
        "got: {err}"
    );
}

#[tokio::test]
async fn channel_secret_telegram_bot_token_roundtrip() {
    let dir = std::env::temp_dir().join(format!("rain_test_tg_bot_token_{}", uuid::Uuid::new_v4()));
    fs::create_dir_all(&dir).await.unwrap();

    let plaintext_token = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11";

    let mut config = Config::default();
    config.workspace_dir = dir.join("workspace");
    config.config_path = dir.join("config.toml");
    config.channels_config.telegram = Some(TelegramConfig {
        bot_token: plaintext_token.into(),
        allowed_users: vec!["user1".into()],
        stream_mode: StreamMode::default(),
        draft_update_interval_ms: default_draft_update_interval_ms(),
        interrupt_on_new_message: false,
        mention_only: false,
        ack_reactions: None,
        proxy_url: None,
    });

    // Save (triggers encryption)
    config.save().await.unwrap();

    // Read raw TOML and verify plaintext token is NOT present
    let raw_toml = tokio::fs::read_to_string(&config.config_path)
        .await
        .unwrap();
    assert!(
        !raw_toml.contains(plaintext_token),
        "Saved TOML must not contain the plaintext bot_token"
    );

    // Parse stored TOML and verify the value is encrypted
    let stored: Config = toml::from_str(&raw_toml).unwrap();
    let stored_token = &stored.channels_config.telegram.as_ref().unwrap().bot_token;
    assert!(
        crate::security::SecretStore::is_encrypted(stored_token),
        "Stored bot_token must be marked as encrypted"
    );

    // Decrypt and verify it matches the original plaintext
    let store = crate::security::SecretStore::new(&dir, true);
    assert_eq!(store.decrypt(stored_token).unwrap(), plaintext_token);

    // Simulate a full load: deserialize then decrypt (mirrors load_or_init logic)
    let mut loaded: Config = toml::from_str(&raw_toml).unwrap();
    loaded.config_path = dir.join("config.toml");
    let load_store = crate::security::SecretStore::new(&dir, loaded.secrets.encrypt);
    if let Some(ref mut tg) = loaded.channels_config.telegram {
        decrypt_secret(
            &load_store,
            &mut tg.bot_token,
            "config.channels_config.telegram.bot_token",
        )
        .unwrap();
    }
    assert_eq!(
        loaded.channels_config.telegram.as_ref().unwrap().bot_token,
        plaintext_token,
        "Loaded bot_token must match the original plaintext after decryption"
    );

    let _ = fs::remove_dir_all(&dir).await;
}

#[test]
async fn security_validation_rejects_unknown_domain_category() {
    let mut config = Config::default();
    config.security.otp.gated_domain_categories = vec!["not_real".into()];

    let err = config
        .validate()
        .expect_err("expected unknown domain category");
    assert!(err.to_string().contains("gated_domain_categories"));
}

#[test]
async fn security_validation_rejects_zero_token_ttl() {
    let mut config = Config::default();
    config.security.otp.token_ttl_secs = 0;

    let err = config
        .validate()
        .expect_err("expected ttl validation failure");
    assert!(err.to_string().contains("token_ttl_secs"));
}

// ── MCP config validation ─────────────────────────────────────────────

fn stdio_server(name: &str, command: &str) -> McpServerConfig {
    McpServerConfig {
        name: name.to_string(),
        transport: McpTransport::Stdio,
        command: command.to_string(),
        ..Default::default()
    }
}

fn http_server(name: &str, url: &str) -> McpServerConfig {
    McpServerConfig {
        name: name.to_string(),
        transport: McpTransport::Http,
        url: Some(url.to_string()),
        ..Default::default()
    }
}

fn sse_server(name: &str, url: &str) -> McpServerConfig {
    McpServerConfig {
        name: name.to_string(),
        transport: McpTransport::Sse,
        url: Some(url.to_string()),
        ..Default::default()
    }
}

#[test]
async fn validate_mcp_config_empty_servers_ok() {
    let cfg = McpConfig::default();
    assert!(validate_mcp_config(&cfg).is_ok());
}

#[test]
async fn validate_mcp_config_valid_stdio_ok() {
    let cfg = McpConfig {
        enabled: true,
        servers: vec![stdio_server("fs", "/usr/bin/mcp-fs")],
        ..Default::default()
    };
    assert!(validate_mcp_config(&cfg).is_ok());
}

#[test]
async fn validate_mcp_config_valid_http_ok() {
    let cfg = McpConfig {
        enabled: true,
        servers: vec![http_server("svc", "http://localhost:8080/mcp")],
        ..Default::default()
    };
    assert!(validate_mcp_config(&cfg).is_ok());
}

#[test]
async fn validate_mcp_config_valid_sse_ok() {
    let cfg = McpConfig {
        enabled: true,
        servers: vec![sse_server("svc", "https://example.com/events")],
        ..Default::default()
    };
    assert!(validate_mcp_config(&cfg).is_ok());
}

#[test]
async fn validate_mcp_config_rejects_empty_name() {
    let cfg = McpConfig {
        enabled: true,
        servers: vec![stdio_server("", "/usr/bin/tool")],
        ..Default::default()
    };
    let err = validate_mcp_config(&cfg).expect_err("empty name should fail");
    assert!(
        err.to_string().contains("name must not be empty"),
        "got: {err}"
    );
}

#[test]
async fn validate_mcp_config_rejects_whitespace_name() {
    let cfg = McpConfig {
        enabled: true,
        servers: vec![stdio_server("   ", "/usr/bin/tool")],
        ..Default::default()
    };
    let err = validate_mcp_config(&cfg).expect_err("whitespace name should fail");
    assert!(
        err.to_string().contains("name must not be empty"),
        "got: {err}"
    );
}

#[test]
async fn validate_mcp_config_rejects_duplicate_names() {
    let cfg = McpConfig {
        enabled: true,
        servers: vec![
            stdio_server("fs", "/usr/bin/mcp-a"),
            stdio_server("fs", "/usr/bin/mcp-b"),
        ],
        ..Default::default()
    };
    let err = validate_mcp_config(&cfg).expect_err("duplicate name should fail");
    assert!(err.to_string().contains("duplicate name"), "got: {err}");
}

#[test]
async fn validate_mcp_config_rejects_zero_timeout() {
    let mut server = stdio_server("fs", "/usr/bin/mcp-fs");
    server.tool_timeout_secs = Some(0);
    let cfg = McpConfig {
        enabled: true,
        servers: vec![server],
        ..Default::default()
    };
    let err = validate_mcp_config(&cfg).expect_err("zero timeout should fail");
    assert!(err.to_string().contains("greater than 0"), "got: {err}");
}

#[test]
async fn validate_mcp_config_rejects_timeout_exceeding_max() {
    let mut server = stdio_server("fs", "/usr/bin/mcp-fs");
    server.tool_timeout_secs = Some(MCP_MAX_TOOL_TIMEOUT_SECS + 1);
    let cfg = McpConfig {
        enabled: true,
        servers: vec![server],
        ..Default::default()
    };
    let err = validate_mcp_config(&cfg).expect_err("oversized timeout should fail");
    assert!(err.to_string().contains("exceeds max"), "got: {err}");
}

#[test]
async fn validate_mcp_config_allows_max_timeout_exactly() {
    let mut server = stdio_server("fs", "/usr/bin/mcp-fs");
    server.tool_timeout_secs = Some(MCP_MAX_TOOL_TIMEOUT_SECS);
    let cfg = McpConfig {
        enabled: true,
        servers: vec![server],
        ..Default::default()
    };
    assert!(validate_mcp_config(&cfg).is_ok());
}

#[test]
async fn validate_mcp_config_rejects_stdio_with_empty_command() {
    let cfg = McpConfig {
        enabled: true,
        servers: vec![stdio_server("fs", "")],
        ..Default::default()
    };
    let err = validate_mcp_config(&cfg).expect_err("empty command should fail");
    assert!(
        err.to_string().contains("requires non-empty command"),
        "got: {err}"
    );
}

#[test]
async fn validate_mcp_config_rejects_http_without_url() {
    let cfg = McpConfig {
        enabled: true,
        servers: vec![McpServerConfig {
            name: "svc".to_string(),
            transport: McpTransport::Http,
            url: None,
            ..Default::default()
        }],
        ..Default::default()
    };
    let err = validate_mcp_config(&cfg).expect_err("http without url should fail");
    assert!(err.to_string().contains("requires url"), "got: {err}");
}

#[test]
async fn validate_mcp_config_rejects_sse_without_url() {
    let cfg = McpConfig {
        enabled: true,
        servers: vec![McpServerConfig {
            name: "svc".to_string(),
            transport: McpTransport::Sse,
            url: None,
            ..Default::default()
        }],
        ..Default::default()
    };
    let err = validate_mcp_config(&cfg).expect_err("sse without url should fail");
    assert!(err.to_string().contains("requires url"), "got: {err}");
}

#[test]
async fn validate_mcp_config_rejects_non_http_scheme() {
    let cfg = McpConfig {
        enabled: true,
        servers: vec![http_server("svc", "ftp://example.com/mcp")],
        ..Default::default()
    };
    let err = validate_mcp_config(&cfg).expect_err("non-http scheme should fail");
    assert!(err.to_string().contains("http/https"), "got: {err}");
}

#[test]
async fn validate_mcp_config_rejects_invalid_url() {
    let cfg = McpConfig {
        enabled: true,
        servers: vec![http_server("svc", "not a url at all !!!")],
        ..Default::default()
    };
    let err = validate_mcp_config(&cfg).expect_err("invalid url should fail");
    assert!(err.to_string().contains("valid URL"), "got: {err}");
}

#[test]
async fn mcp_config_default_disabled_with_empty_servers() {
    let cfg = McpConfig::default();
    assert!(!cfg.enabled);
    assert!(cfg.servers.is_empty());
}

#[test]
async fn mcp_transport_serde_roundtrip_lowercase() {
    let cases = [
        (McpTransport::Stdio, "\"stdio\""),
        (McpTransport::Http, "\"http\""),
        (McpTransport::Sse, "\"sse\""),
    ];
    for (variant, expected_json) in &cases {
        let serialized = serde_json::to_string(variant).expect("serialize");
        assert_eq!(&serialized, expected_json, "variant: {variant:?}");
        let deserialized: McpTransport = serde_json::from_str(expected_json).expect("deserialize");
        assert_eq!(&deserialized, variant);
    }
}

#[test]
async fn swarm_strategy_roundtrip() {
    let cases = vec![
        (SwarmStrategy::Sequential, "\"sequential\""),
        (SwarmStrategy::Parallel, "\"parallel\""),
        (SwarmStrategy::Router, "\"router\""),
    ];
    for (variant, expected_json) in &cases {
        let serialized = serde_json::to_string(variant).expect("serialize");
        assert_eq!(&serialized, expected_json, "variant: {variant:?}");
        let deserialized: SwarmStrategy = serde_json::from_str(expected_json).expect("deserialize");
        assert_eq!(&deserialized, variant);
    }
}

#[test]
async fn swarm_config_deserializes_with_defaults() {
    let toml_str = r#"
        agents = ["researcher", "writer"]
        strategy = "sequential"
    "#;
    let config: SwarmConfig = toml::from_str(toml_str).expect("deserialize");
    assert_eq!(config.agents, vec!["researcher", "writer"]);
    assert_eq!(config.strategy, SwarmStrategy::Sequential);
    assert!(config.router_prompt.is_none());
    assert!(config.description.is_none());
    assert_eq!(config.timeout_secs, 300);
}

#[test]
async fn swarm_config_deserializes_full() {
    let toml_str = r#"
        agents = ["a", "b", "c"]
        strategy = "router"
        router_prompt = "Pick the best."
        description = "Multi-agent router"
        timeout_secs = 120
    "#;
    let config: SwarmConfig = toml::from_str(toml_str).expect("deserialize");
    assert_eq!(config.agents.len(), 3);
    assert_eq!(config.strategy, SwarmStrategy::Router);
    assert_eq!(config.router_prompt.as_deref(), Some("Pick the best."));
    assert_eq!(config.description.as_deref(), Some("Multi-agent router"));
    assert_eq!(config.timeout_secs, 120);
}

#[test]
async fn config_with_swarms_section_deserializes() {
    let toml_str = r#"
        [agents.researcher]
        provider = "ollama"
        model = "llama3"

        [agents.writer]
        provider = "openrouter"
        model = "claude-sonnet"

        [swarms.pipeline]
        agents = ["researcher", "writer"]
        strategy = "sequential"
    "#;
    let config = parse_test_config(toml_str);
    assert_eq!(config.agents.len(), 2);
    assert_eq!(config.swarms.len(), 1);
    assert!(config.swarms.contains_key("pipeline"));
}

#[tokio::test]
async fn nevis_client_secret_encrypt_decrypt_roundtrip() {
    let dir = std::env::temp_dir().join(format!("rain_test_nevis_secret_{}", uuid::Uuid::new_v4()));
    fs::create_dir_all(&dir).await.unwrap();

    let plaintext_secret = "nevis-test-client-secret-value";

    let mut config = Config::default();
    config.workspace_dir = dir.join("workspace");
    config.config_path = dir.join("config.toml");
    config.security.nevis.client_secret = Some(plaintext_secret.into());

    // Save (triggers encryption)
    config.save().await.unwrap();

    // Read raw TOML and verify plaintext secret is NOT present
    let raw_toml = tokio::fs::read_to_string(&config.config_path)
        .await
        .unwrap();
    assert!(
        !raw_toml.contains(plaintext_secret),
        "Saved TOML must not contain the plaintext client_secret"
    );

    // Parse stored TOML and verify the value is encrypted
    let stored: Config = toml::from_str(&raw_toml).unwrap();
    let stored_secret = stored.security.nevis.client_secret.as_ref().unwrap();
    assert!(
        crate::security::SecretStore::is_encrypted(stored_secret),
        "Stored client_secret must be marked as encrypted"
    );

    // Decrypt and verify it matches the original plaintext
    let store = crate::security::SecretStore::new(&dir, true);
    assert_eq!(store.decrypt(stored_secret).unwrap(), plaintext_secret);

    // Simulate a full load: deserialize then decrypt (mirrors load_or_init logic)
    let mut loaded: Config = toml::from_str(&raw_toml).unwrap();
    loaded.config_path = dir.join("config.toml");
    let load_store = crate::security::SecretStore::new(&dir, loaded.secrets.encrypt);
    decrypt_optional_secret(
        &load_store,
        &mut loaded.security.nevis.client_secret,
        "config.security.nevis.client_secret",
    )
    .unwrap();
    assert_eq!(
        loaded.security.nevis.client_secret.as_deref().unwrap(),
        plaintext_secret,
        "Loaded client_secret must match the original plaintext after decryption"
    );

    let _ = fs::remove_dir_all(&dir).await;
}

// ══════════════════════════════════════════════════════════
// Nevis config validation tests
// ══════════════════════════════════════════════════════════

#[test]
async fn nevis_config_validate_disabled_accepts_empty_fields() {
    let cfg = NevisConfig::default();
    assert!(!cfg.enabled);
    assert!(cfg.validate().is_ok());
}

#[test]
async fn nevis_config_validate_rejects_empty_instance_url() {
    let cfg = NevisConfig {
        enabled: true,
        instance_url: String::new(),
        client_id: "test-client".into(),
        ..NevisConfig::default()
    };
    let err = cfg.validate().unwrap_err();
    assert!(err.contains("instance_url"));
}

#[test]
async fn nevis_config_validate_rejects_empty_client_id() {
    let cfg = NevisConfig {
        enabled: true,
        instance_url: "https://nevis.example.com".into(),
        client_id: String::new(),
        ..NevisConfig::default()
    };
    let err = cfg.validate().unwrap_err();
    assert!(err.contains("client_id"));
}

#[test]
async fn nevis_config_validate_rejects_empty_realm() {
    let cfg = NevisConfig {
        enabled: true,
        instance_url: "https://nevis.example.com".into(),
        client_id: "test-client".into(),
        realm: String::new(),
        ..NevisConfig::default()
    };
    let err = cfg.validate().unwrap_err();
    assert!(err.contains("realm"));
}

#[test]
async fn nevis_config_validate_rejects_local_without_jwks() {
    let cfg = NevisConfig {
        enabled: true,
        instance_url: "https://nevis.example.com".into(),
        client_id: "test-client".into(),
        token_validation: "local".into(),
        jwks_url: None,
        ..NevisConfig::default()
    };
    let err = cfg.validate().unwrap_err();
    assert!(err.contains("jwks_url"));
}

#[test]
async fn nevis_config_validate_rejects_zero_session_timeout() {
    let cfg = NevisConfig {
        enabled: true,
        instance_url: "https://nevis.example.com".into(),
        client_id: "test-client".into(),
        token_validation: "remote".into(),
        session_timeout_secs: 0,
        ..NevisConfig::default()
    };
    let err = cfg.validate().unwrap_err();
    assert!(err.contains("session_timeout_secs"));
}

#[test]
async fn nevis_config_validate_accepts_valid_enabled_config() {
    let cfg = NevisConfig {
        enabled: true,
        instance_url: "https://nevis.example.com".into(),
        realm: "master".into(),
        client_id: "test-client".into(),
        token_validation: "remote".into(),
        session_timeout_secs: 3600,
        ..NevisConfig::default()
    };
    assert!(cfg.validate().is_ok());
}

#[test]
async fn nevis_config_validate_rejects_invalid_token_validation() {
    let cfg = NevisConfig {
        enabled: true,
        instance_url: "https://nevis.example.com".into(),
        realm: "master".into(),
        client_id: "test-client".into(),
        token_validation: "invalid_mode".into(),
        session_timeout_secs: 3600,
        ..NevisConfig::default()
    };
    let err = cfg.validate().unwrap_err();
    assert!(
        err.contains("invalid value 'invalid_mode'"),
        "Expected invalid token_validation error, got: {err}"
    );
}

#[test]
async fn nevis_config_debug_redacts_client_secret() {
    let cfg = NevisConfig {
        client_secret: Some("super-secret".into()),
        ..NevisConfig::default()
    };
    let debug_output = format!("{:?}", cfg);
    assert!(
        !debug_output.contains("super-secret"),
        "Debug output must not contain the raw client_secret"
    );
    assert!(
        debug_output.contains("[REDACTED]"),
        "Debug output must show [REDACTED] for client_secret"
    );
}

#[test]
async fn telegram_config_ack_reactions_false_deserializes() {
    let toml_str = r#"
        bot_token = "123:ABC"
        allowed_users = ["alice"]
        ack_reactions = false
    "#;
    let cfg: TelegramConfig = toml::from_str(toml_str).unwrap();
    assert_eq!(cfg.ack_reactions, Some(false));
}

#[test]
async fn telegram_config_ack_reactions_true_deserializes() {
    let toml_str = r#"
        bot_token = "123:ABC"
        allowed_users = ["alice"]
        ack_reactions = true
    "#;
    let cfg: TelegramConfig = toml::from_str(toml_str).unwrap();
    assert_eq!(cfg.ack_reactions, Some(true));
}

#[test]
async fn telegram_config_ack_reactions_missing_defaults_to_none() {
    let toml_str = r#"
        bot_token = "123:ABC"
        allowed_users = ["alice"]
    "#;
    let cfg: TelegramConfig = toml::from_str(toml_str).unwrap();
    assert_eq!(cfg.ack_reactions, None);
}

#[test]
async fn telegram_config_ack_reactions_channel_overrides_top_level() {
    let tg_toml = r#"
        bot_token = "123:ABC"
        allowed_users = ["alice"]
        ack_reactions = false
    "#;
    let tg: TelegramConfig = toml::from_str(tg_toml).unwrap();
    let top_level_ack = true;
    let effective = tg.ack_reactions.unwrap_or(top_level_ack);
    assert!(
        !effective,
        "channel-level false must override top-level true"
    );
}

#[test]
async fn telegram_config_ack_reactions_falls_back_to_top_level() {
    let tg_toml = r#"
        bot_token = "123:ABC"
        allowed_users = ["alice"]
    "#;
    let tg: TelegramConfig = toml::from_str(tg_toml).unwrap();
    let top_level_ack = false;
    let effective = tg.ack_reactions.unwrap_or(top_level_ack);
    assert!(
        !effective,
        "must fall back to top-level false when channel omits field"
    );
}

#[test]
async fn google_workspace_allowed_operations_deserialize_from_toml() {
    let toml_str = r#"
        enabled = true

        [[allowed_operations]]
        service = "gmail"
        resource = "users"
        sub_resource = "drafts"
        methods = ["create", "update"]
    "#;

    let cfg: GoogleWorkspaceConfig = toml::from_str(toml_str).unwrap();
    assert_eq!(cfg.allowed_operations.len(), 1);
    assert_eq!(cfg.allowed_operations[0].service, "gmail");
    assert_eq!(cfg.allowed_operations[0].resource, "users");
    assert_eq!(
        cfg.allowed_operations[0].sub_resource.as_deref(),
        Some("drafts")
    );
    assert_eq!(
        cfg.allowed_operations[0].methods,
        vec!["create".to_string(), "update".to_string()]
    );
}

#[test]
async fn google_workspace_allowed_operations_deserialize_without_sub_resource() {
    let toml_str = r#"
        enabled = true

        [[allowed_operations]]
        service = "drive"
        resource = "files"
        methods = ["list", "get"]
    "#;

    let cfg: GoogleWorkspaceConfig = toml::from_str(toml_str).unwrap();
    assert_eq!(cfg.allowed_operations[0].sub_resource, None);
}

#[test]
async fn config_validate_accepts_google_workspace_allowed_operations() {
    let mut cfg = Config::default();
    cfg.google_workspace.enabled = true;
    cfg.google_workspace.allowed_services = vec!["gmail".into()];
    cfg.google_workspace.allowed_operations = vec![GoogleWorkspaceAllowedOperation {
        service: "gmail".into(),
        resource: "users".into(),
        sub_resource: Some("drafts".into()),
        methods: vec!["create".into(), "update".into()],
    }];

    cfg.validate().unwrap();
}

#[test]
async fn config_validate_rejects_duplicate_google_workspace_allowed_operations() {
    let mut cfg = Config::default();
    cfg.google_workspace.enabled = true;
    cfg.google_workspace.allowed_services = vec!["gmail".into()];
    cfg.google_workspace.allowed_operations = vec![
        GoogleWorkspaceAllowedOperation {
            service: "gmail".into(),
            resource: "users".into(),
            sub_resource: Some("drafts".into()),
            methods: vec!["create".into()],
        },
        GoogleWorkspaceAllowedOperation {
            service: "gmail".into(),
            resource: "users".into(),
            sub_resource: Some("drafts".into()),
            methods: vec!["update".into()],
        },
    ];

    let err = cfg.validate().unwrap_err().to_string();
    assert!(err.contains("duplicate service/resource/sub_resource entry"));
}

#[test]
async fn config_validate_rejects_operation_service_not_in_allowed_services() {
    let mut cfg = Config::default();
    cfg.google_workspace.enabled = true;
    cfg.google_workspace.allowed_services = vec!["gmail".into()];
    cfg.google_workspace.allowed_operations = vec![GoogleWorkspaceAllowedOperation {
        service: "drive".into(), // drive is not in allowed_services
        resource: "files".into(),
        sub_resource: None,
        methods: vec!["list".into()],
    }];

    let err = cfg.validate().unwrap_err().to_string();
    assert!(
        err.contains("not in the effective allowed_services"),
        "expected not-in-allowed_services error, got: {err}"
    );
}

#[test]
async fn config_validate_accepts_default_service_when_allowed_services_empty() {
    // When allowed_services is empty the validator uses DEFAULT_GWS_SERVICES.
    // A known default service must pass.
    let mut cfg = Config::default();
    cfg.google_workspace.enabled = true;
    // allowed_services deliberately left empty (falls back to defaults)
    cfg.google_workspace.allowed_operations = vec![GoogleWorkspaceAllowedOperation {
        service: "drive".into(),
        resource: "files".into(),
        sub_resource: None,
        methods: vec!["list".into()],
    }];

    assert!(cfg.validate().is_ok());
}

#[test]
async fn config_validate_rejects_unknown_service_when_allowed_services_empty() {
    // Even with allowed_services empty (using defaults), an operation whose
    // service is not in DEFAULT_GWS_SERVICES must fail validation — not silently
    // pass through to be rejected at runtime.
    let mut cfg = Config::default();
    cfg.google_workspace.enabled = true;
    // allowed_services deliberately left empty
    cfg.google_workspace.allowed_operations = vec![GoogleWorkspaceAllowedOperation {
        service: "not_a_real_service".into(),
        resource: "files".into(),
        sub_resource: None,
        methods: vec!["list".into()],
    }];

    let err = cfg.validate().unwrap_err().to_string();
    assert!(
        err.contains("not in the effective allowed_services"),
        "expected effective-allowed_services error, got: {err}"
    );
}

// ── Bootstrap files ─────────────────────────────────────

#[test]
async fn ensure_bootstrap_files_creates_missing_files() {
    let tmp = TempDir::new().unwrap();
    let ws = tmp.path().join("workspace");
    tokio::fs::create_dir_all(&ws).await.unwrap();

    ensure_bootstrap_files(&ws).await.unwrap();

    let soul = tokio::fs::read_to_string(ws.join("SOUL.md")).await.unwrap();
    let identity = tokio::fs::read_to_string(ws.join("IDENTITY.md"))
        .await
        .unwrap();
    assert!(soul.contains("SOUL.md"));
    assert!(identity.contains("IDENTITY.md"));
}

#[test]
async fn ensure_bootstrap_files_does_not_overwrite_existing() {
    let tmp = TempDir::new().unwrap();
    let ws = tmp.path().join("workspace");
    tokio::fs::create_dir_all(&ws).await.unwrap();

    let custom = "# My custom SOUL";
    tokio::fs::write(ws.join("SOUL.md"), custom).await.unwrap();

    ensure_bootstrap_files(&ws).await.unwrap();

    let soul = tokio::fs::read_to_string(ws.join("SOUL.md")).await.unwrap();
    assert_eq!(
        soul, custom,
        "ensure_bootstrap_files must not overwrite existing files"
    );

    // IDENTITY.md should still be created since it was missing
    let identity = tokio::fs::read_to_string(ws.join("IDENTITY.md"))
        .await
        .unwrap();
    assert!(identity.contains("IDENTITY.md"));
}
