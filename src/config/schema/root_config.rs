use super::*;

/// Top-level R.A.I.N. configuration, loaded from `config.toml`.
///
/// Resolution order: `rain_WORKSPACE` env → `active_workspace.toml` marker → `~/.R.A.I.N./config.toml`.
#[derive(Debug, Clone, Serialize, Deserialize, JsonSchema)]
pub struct Config {
    /// Workspace directory - computed from home, not serialized
    #[serde(skip)]
    pub workspace_dir: PathBuf,
    /// Path to config.toml - computed from home, not serialized
    #[serde(skip)]
    pub config_path: PathBuf,
    /// API key for the selected provider. Overridden by `rain_API_KEY` or `API_KEY` env vars.
    pub api_key: Option<String>,
    /// Base URL override for provider API (e.g. "http://10.0.0.1:11434" for remote Ollama)
    pub api_url: Option<String>,
    /// Custom API path suffix for OpenAI-compatible / custom providers
    /// (e.g. "/v2/generate" instead of the default "/v1/chat/completions").
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub api_path: Option<String>,
    /// Default provider ID or alias (e.g. `"openrouter"`, `"ollama"`, `"anthropic"`). Default: `"openrouter"`.
    #[serde(alias = "model_provider")]
    pub default_provider: Option<String>,
    /// Default model routed through the selected provider (e.g. `"anthropic/claude-sonnet-4-6"`).
    #[serde(alias = "model")]
    pub default_model: Option<String>,
    /// Optional named provider profiles keyed by id (Codex app-server compatible layout).
    #[serde(default)]
    pub model_providers: HashMap<String, ModelProviderConfig>,
    /// Default model temperature (0.0–2.0). Default: `0.7`.
    #[serde(
        default = "default_temperature",
        deserialize_with = "deserialize_temperature"
    )]
    pub default_temperature: f64,

    /// HTTP request timeout in seconds for LLM provider API calls. Default: `120`.
    ///
    /// Increase for slower backends (e.g., llama.cpp on constrained hardware)
    /// that need more time processing large contexts.
    #[serde(default = "default_provider_timeout_secs")]
    pub provider_timeout_secs: u64,

    /// Extra HTTP headers to include in LLM provider API requests.
    ///
    /// Some providers require specific headers (e.g., `User-Agent`, `HTTP-Referer`,
    /// `X-Title`) for request routing or policy enforcement. Headers defined here
    /// augment (and override) the program's default headers.
    ///
    /// Can also be set via `rain_EXTRA_HEADERS` environment variable using
    /// the format `Key:Value,Key2:Value2`. Env var headers override config file headers.
    #[serde(default)]
    pub extra_headers: HashMap<String, String>,

    /// Observability backend configuration (`[observability]`).
    #[serde(default)]
    pub observability: ObservabilityConfig,

    /// Autonomy and security policy configuration (`[autonomy]`).
    #[serde(default)]
    pub autonomy: AutonomyConfig,

    /// Security subsystem configuration (`[security]`).
    #[serde(default)]
    pub security: SecurityConfig,

    /// Backup tool configuration (`[backup]`).
    #[serde(default)]
    pub backup: BackupConfig,

    /// Data retention and purge configuration (`[data_retention]`).
    #[serde(default)]
    pub data_retention: DataRetentionConfig,

    /// Cloud transformation accelerator configuration (`[cloud_ops]`).
    #[serde(default)]
    pub cloud_ops: CloudOpsConfig,

    /// Conversational AI agent builder configuration (`[conversational_ai]`).
    ///
    /// Experimental / future feature — not yet wired into the agent runtime.
    /// Omitted from generated config files when disabled (the default).
    /// Existing configs that already contain this section will continue to
    /// deserialize correctly thanks to `#[serde(default)]`.
    #[serde(default, skip_serializing_if = "ConversationalAiConfig::is_disabled")]
    pub conversational_ai: ConversationalAiConfig,

    /// Managed cybersecurity service configuration (`[security_ops]`).
    #[serde(default)]
    pub security_ops: SecurityOpsConfig,

    /// Runtime adapter configuration (`[runtime]`). Controls native vs Docker execution.
    #[serde(default)]
    pub runtime: RuntimeConfig,

    /// Reliability settings: retries, fallback providers, backoff (`[reliability]`).
    #[serde(default)]
    pub reliability: ReliabilityConfig,

    /// Scheduler configuration for periodic task execution (`[scheduler]`).
    #[serde(default)]
    pub scheduler: SchedulerConfig,

    /// Agent orchestration settings (`[agent]`).
    #[serde(default)]
    pub agent: AgentConfig,

    /// Pacing controls for slow/local LLM workloads (`[pacing]`).
    #[serde(default)]
    pub pacing: PacingConfig,

    /// Skills loading and community repository behavior (`[skills]`).
    #[serde(default)]
    pub skills: SkillsConfig,

    /// Model routing rules — route `hint:<name>` to specific provider+model combos.
    #[serde(default)]
    pub model_routes: Vec<ModelRouteConfig>,

    /// Embedding routing rules — route `hint:<name>` to specific provider+model combos.
    #[serde(default)]
    pub embedding_routes: Vec<EmbeddingRouteConfig>,

    /// Automatic query classification — maps user messages to model hints.
    #[serde(default)]
    pub query_classification: QueryClassificationConfig,

    /// Heartbeat configuration for periodic health pings (`[heartbeat]`).
    #[serde(default)]
    pub heartbeat: HeartbeatConfig,

    /// Cron job configuration (`[cron]`).
    #[serde(default)]
    pub cron: CronConfig,

    /// Channel configurations: Telegram, Discord, Slack, etc. (`[channels_config]`).
    #[serde(default)]
    pub channels_config: ChannelsConfig,

    /// Memory backend configuration: sqlite, markdown, embeddings (`[memory]`).
    #[serde(default)]
    pub memory: MemoryConfig,

    /// Persistent storage provider configuration (`[storage]`).
    #[serde(default)]
    pub storage: StorageConfig,

    /// Tunnel configuration for exposing the gateway publicly (`[tunnel]`).
    #[serde(default)]
    pub tunnel: TunnelConfig,

    /// Gateway server configuration: host, port, pairing, rate limits (`[gateway]`).
    #[serde(default)]
    pub gateway: GatewayConfig,

    /// Composio managed OAuth tools integration (`[composio]`).
    #[serde(default)]
    pub composio: ComposioConfig,

    /// Microsoft 365 Graph API integration (`[microsoft365]`).
    #[serde(default)]
    pub microsoft365: Microsoft365Config,

    /// Secrets encryption configuration (`[secrets]`).
    #[serde(default)]
    pub secrets: SecretsConfig,

    /// Browser automation configuration (`[browser]`).
    #[serde(default)]
    pub browser: BrowserConfig,

    /// Browser delegation configuration (`[browser_delegate]`).
    ///
    /// Delegates browser-based tasks to a browser-capable CLI subprocess (e.g.
    /// Claude Code with `claude-in-chrome` MCP tools). Useful for interacting
    /// with corporate web apps (Teams, Outlook, Jira, Confluence) that lack
    /// direct API access. A persistent Chrome profile can be configured so SSO
    /// sessions survive across invocations.
    ///
    /// Fields:
    /// - `enabled` (`bool`, default `false`) — enable the browser delegation tool.
    /// - `cli_binary` (`String`, default `"claude"`) — CLI binary to spawn for browser tasks.
    /// - `chrome_profile_dir` (`String`, default `""`) — Chrome user-data directory for
    ///   persistent SSO sessions. When empty, a fresh profile is used each invocation.
    /// - `allowed_domains` (`Vec<String>`, default `[]`) — allowlist of domains the browser
    ///   may navigate to. Empty means all non-blocked domains are permitted.
    /// - `blocked_domains` (`Vec<String>`, default `[]`) — denylist of domains. Blocked
    ///   domains take precedence over allowed domains.
    /// - `task_timeout_secs` (`u64`, default `120`) — per-task timeout in seconds.
    ///
    /// Compatibility: additive and disabled by default; existing configs remain valid when omitted.
    /// Rollback/migration: remove `[browser_delegate]` or keep `enabled = false` to disable.
    #[serde(default)]
    pub browser_delegate: crate::tools::browser_delegate::BrowserDelegateConfig,

    /// HTTP request tool configuration (`[http_request]`).
    #[serde(default)]
    pub http_request: HttpRequestConfig,

    /// Multimodal (image) handling configuration (`[multimodal]`).
    #[serde(default)]
    pub multimodal: MultimodalConfig,

    /// Web fetch tool configuration (`[web_fetch]`).
    #[serde(default)]
    pub web_fetch: WebFetchConfig,

    /// Text browser tool configuration (`[text_browser]`).
    #[serde(default)]
    pub text_browser: TextBrowserConfig,

    /// Web search tool configuration (`[web_search]`).
    #[serde(default)]
    pub web_search: WebSearchConfig,

    /// Project delivery intelligence configuration (`[project_intel]`).
    #[serde(default)]
    pub project_intel: ProjectIntelConfig,

    /// Google Workspace CLI (`gws`) tool configuration (`[google_workspace]`).
    #[serde(default)]
    pub google_workspace: GoogleWorkspaceConfig,

    /// Proxy configuration for outbound HTTP/HTTPS/SOCKS5 traffic (`[proxy]`).
    #[serde(default)]
    pub proxy: ProxyConfig,

    /// Identity format configuration: OpenClaw or AIEOS (`[identity]`).
    #[serde(default)]
    pub identity: IdentityConfig,

    /// Cost tracking and budget enforcement configuration (`[cost]`).
    #[serde(default)]
    pub cost: CostConfig,

    /// Peripheral board configuration for hardware integration (`[peripherals]`).
    #[serde(default)]
    pub peripherals: PeripheralsConfig,

    /// Delegate tool global default configuration (`[delegate]`).
    #[serde(default)]
    pub delegate: DelegateToolConfig,

    /// Delegate agent configurations for multi-agent workflows.
    #[serde(default)]
    pub agents: HashMap<String, DelegateAgentConfig>,

    /// Swarm configurations for multi-agent orchestration.
    #[serde(default)]
    pub swarms: HashMap<String, SwarmConfig>,

    /// Hooks configuration (lifecycle hooks and built-in hook toggles).
    #[serde(default)]
    pub hooks: HooksConfig,

    /// Hardware configuration (wizard-driven physical world setup).
    #[serde(default)]
    pub hardware: HardwareConfig,

    /// Voice transcription configuration (Whisper API via Groq).
    #[serde(default)]
    pub transcription: TranscriptionConfig,

    /// Text-to-Speech configuration (`[tts]`).
    #[serde(default)]
    pub tts: TtsConfig,

    /// External MCP server connections (`[mcp]`).
    #[serde(default, alias = "mcpServers")]
    pub mcp: McpConfig,

    /// Dynamic node discovery configuration (`[nodes]`).
    #[serde(default)]
    pub nodes: NodesConfig,

    /// Multi-client workspace isolation configuration (`[workspace]`).
    #[serde(default)]
    pub workspace: WorkspaceConfig,

    /// Notion integration configuration (`[notion]`).
    #[serde(default)]
    pub notion: NotionConfig,

    /// Jira integration configuration (`[jira]`).
    #[serde(default)]
    pub jira: JiraConfig,

    /// Secure inter-node transport configuration (`[node_transport]`).
    #[serde(default)]
    pub node_transport: NodeTransportConfig,

    /// Knowledge graph configuration (`[knowledge]`).
    #[serde(default)]
    pub knowledge: KnowledgeConfig,

    /// LinkedIn integration configuration (`[linkedin]`).
    #[serde(default)]
    pub linkedin: LinkedInConfig,

    /// Plugin system configuration (`[plugins]`).
    #[serde(default)]
    pub plugins: PluginsConfig,

    /// Locale for tool descriptions (e.g. `"en"`, `"zh-CN"`).
    ///
    /// When set, tool descriptions shown in system prompts are loaded from
    /// `tool_descriptions/<locale>.toml`. Falls back to English, then to
    /// hardcoded descriptions.
    ///
    /// If omitted or empty, the locale is auto-detected from `rain_LOCALE`,
    /// `LANG`, or `LC_ALL` environment variables (defaulting to `"en"`).
    #[serde(default)]
    pub locale: Option<String>,

    /// Verifiable Intent (VI) credential verification and issuance (`[verifiable_intent]`).
    #[serde(default)]
    pub verifiable_intent: VerifiableIntentConfig,

    /// Claude Code tool configuration (`[claude_code]`).
    #[serde(default)]
    pub claude_code: ClaudeCodeConfig,
}

/// Multi-client workspace isolation configuration.
///
/// When enabled, each client engagement gets an isolated workspace with
/// separate memory, audit, secrets, and tool restrictions.
#[allow(clippy::struct_excessive_bools)]
#[derive(Debug, Clone, Serialize, Deserialize, JsonSchema)]
pub struct WorkspaceConfig {
    /// Enable workspace isolation. Default: false.
    #[serde(default)]
    pub enabled: bool,
    /// Currently active workspace name.
    #[serde(default)]
    pub active_workspace: Option<String>,
    /// Base directory for workspace profiles.
    #[serde(default = "default_workspaces_dir")]
    pub workspaces_dir: String,
    /// Isolate memory databases per workspace. Default: true.
    #[serde(default = "default_true")]
    pub isolate_memory: bool,
    /// Isolate secrets namespaces per workspace. Default: true.
    #[serde(default = "default_true")]
    pub isolate_secrets: bool,
    /// Isolate audit logs per workspace. Default: true.
    #[serde(default = "default_true")]
    pub isolate_audit: bool,
    /// Allow searching across workspaces. Default: false (security).
    #[serde(default)]
    pub cross_workspace_search: bool,
}

fn default_workspaces_dir() -> String {
    "~/.R.A.I.N./workspaces".to_string()
}

impl Default for WorkspaceConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            active_workspace: None,
            workspaces_dir: default_workspaces_dir(),
            isolate_memory: true,
            isolate_secrets: true,
            isolate_audit: true,
            cross_workspace_search: false,
        }
    }
}

/// Named provider profile definition compatible with Codex app-server style config.
#[derive(Debug, Clone, Serialize, Deserialize, JsonSchema, Default)]
pub struct ModelProviderConfig {
    /// Optional provider type/name override (e.g. "openai", "openai-codex", or custom profile id).
    #[serde(default)]
    pub name: Option<String>,
    /// Optional base URL for OpenAI-compatible endpoints.
    #[serde(default)]
    pub base_url: Option<String>,
    /// Optional custom API path suffix (e.g. "/v2/generate" instead of the
    /// default "/v1/chat/completions"). Only used by OpenAI-compatible / custom providers.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub api_path: Option<String>,
    /// Provider protocol variant ("responses" or "chat_completions").
    #[serde(default)]
    pub wire_api: Option<String>,
    /// If true, load OpenAI auth material (OPENAI_API_KEY or ~/.codex/auth.json).
    #[serde(default)]
    pub requires_openai_auth: bool,
    /// Azure OpenAI resource name (e.g. "my-resource" in https://my-resource.openai.azure.com).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub azure_openai_resource: Option<String>,
    /// Azure OpenAI deployment name (e.g. "gpt-4o").
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub azure_openai_deployment: Option<String>,
    /// Azure OpenAI API version (defaults to "2024-08-01-preview").
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub azure_openai_api_version: Option<String>,
}

// ── Delegate Tool Configuration ─────────────────────────────────

/// Global delegate tool configuration for default timeout values.
#[derive(Debug, Clone, Serialize, Deserialize, JsonSchema)]
pub struct DelegateToolConfig {
    /// Default timeout in seconds for non-agentic sub-agent provider calls.
    /// Can be overridden per-agent in `[agents.<name>]` config.
    /// Default: 120 seconds.
    #[serde(default = "default_delegate_timeout_secs")]
    pub timeout_secs: u64,
    /// Default timeout in seconds for agentic sub-agent runs.
    /// Can be overridden per-agent in `[agents.<name>]` config.
    /// Default: 300 seconds.
    #[serde(default = "default_delegate_agentic_timeout_secs")]
    pub agentic_timeout_secs: u64,
}

impl Default for DelegateToolConfig {
    fn default() -> Self {
        Self {
            timeout_secs: DEFAULT_DELEGATE_TIMEOUT_SECS,
            agentic_timeout_secs: DEFAULT_DELEGATE_AGENTIC_TIMEOUT_SECS,
        }
    }
}

// ── Delegate Agents ──────────────────────────────────────────────

/// Configuration for a delegate sub-agent used by the `delegate` tool.
#[derive(Debug, Clone, Serialize, Deserialize, JsonSchema)]
pub struct DelegateAgentConfig {
    /// Provider name (e.g. "ollama", "openrouter", "anthropic")
    pub provider: String,
    /// Model name
    pub model: String,
    /// Optional system prompt for the sub-agent
    #[serde(default)]
    pub system_prompt: Option<String>,
    /// Optional API key override
    #[serde(default)]
    pub api_key: Option<String>,
    /// Temperature override
    #[serde(default)]
    pub temperature: Option<f64>,
    /// Max recursion depth for nested delegation
    #[serde(default = "default_max_depth")]
    pub max_depth: u32,
    /// Enable agentic sub-agent mode (multi-turn tool-call loop).
    #[serde(default)]
    pub agentic: bool,
    /// Allowlist of tool names available to the sub-agent in agentic mode.
    #[serde(default)]
    pub allowed_tools: Vec<String>,
    /// Maximum tool-call iterations in agentic mode.
    #[serde(default = "default_max_tool_iterations")]
    pub max_iterations: usize,
    /// Optional timeout in seconds for non-agentic sub-agent provider calls.
    /// When `None`, falls back to `[delegate].timeout_secs` (default: 120).
    #[serde(default)]
    pub timeout_secs: Option<u64>,
    /// Optional timeout in seconds for agentic sub-agent runs.
    /// When `None`, falls back to `[delegate].agentic_timeout_secs` (default: 300).
    #[serde(default)]
    pub agentic_timeout_secs: Option<u64>,
    /// Optional skills directory path (relative to workspace root) for scoped skill loading.
    /// When unset or empty, the sub-agent falls back to the default workspace `skills/` directory.
    #[serde(default)]
    pub skills_directory: Option<String>,
}

fn default_delegate_timeout_secs() -> u64 {
    DEFAULT_DELEGATE_TIMEOUT_SECS
}

fn default_delegate_agentic_timeout_secs() -> u64 {
    DEFAULT_DELEGATE_AGENTIC_TIMEOUT_SECS
}

// ── Swarms ──────────────────────────────────────────────────────

/// Orchestration strategy for a swarm of agents.
#[derive(Debug, Clone, Serialize, Deserialize, JsonSchema, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum SwarmStrategy {
    /// Run agents sequentially; each agent's output feeds into the next.
    Sequential,
    /// Run agents in parallel; collect all outputs.
    Parallel,
    /// Use the LLM to pick the best agent for the task.
    Router,
}

/// Configuration for a swarm of coordinated agents.
#[derive(Debug, Clone, Serialize, Deserialize, JsonSchema)]
pub struct SwarmConfig {
    /// Ordered list of agent names (must reference keys in `agents`).
    pub agents: Vec<String>,
    /// Orchestration strategy.
    pub strategy: SwarmStrategy,
    /// System prompt for router strategy (used to pick the best agent).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub router_prompt: Option<String>,
    /// Optional description shown to the LLM when choosing swarms.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
    /// Maximum total timeout for the swarm execution in seconds.
    #[serde(default = "default_swarm_timeout_secs")]
    pub timeout_secs: u64,
}

const DEFAULT_SWARM_TIMEOUT_SECS: u64 = 300;

fn default_swarm_timeout_secs() -> u64 {
    DEFAULT_SWARM_TIMEOUT_SECS
}

/// Valid temperature range for all paths (config, CLI, env override).
pub const TEMPERATURE_RANGE: std::ops::RangeInclusive<f64> = 0.0..=2.0;

/// Default temperature when the field is absent from config.
pub(super) const DEFAULT_TEMPERATURE: f64 = 0.7;

impl Default for Config {
    fn default() -> Self {
        let home =
            UserDirs::new().map_or_else(|| PathBuf::from("."), |u| u.home_dir().to_path_buf());
        let rain_dir = home.join(".R.A.I.N.");

        Self {
            workspace_dir: rain_dir.join("workspace"),
            config_path: rain_dir.join("config.toml"),
            api_key: None,
            api_url: None,
            api_path: None,
            default_provider: Some("openrouter".to_string()),
            default_model: Some("anthropic/claude-sonnet-4.6".to_string()),
            model_providers: HashMap::new(),
            default_temperature: default_temperature(),
            provider_timeout_secs: default_provider_timeout_secs(),
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
            agent: AgentConfig::default(),
            pacing: PacingConfig::default(),
            skills: SkillsConfig::default(),
            model_routes: Vec::new(),
            embedding_routes: Vec::new(),
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
            identity: IdentityConfig::default(),
            cost: CostConfig::default(),
            peripherals: PeripheralsConfig::default(),
            delegate: DelegateToolConfig::default(),
            agents: HashMap::new(),
            swarms: HashMap::new(),
            hooks: HooksConfig::default(),
            hardware: HardwareConfig::default(),
            query_classification: QueryClassificationConfig::default(),
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
        }
    }
}
