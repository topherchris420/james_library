use crate::agent::history::trim_history as trim_chat_history;
use crate::agent::loop_::{
    ModelSwitchState, build_tool_instructions_from_specs, run_tool_call_loop_with_policy,
};
use crate::agent::manifest::AgentManifest;
use crate::agent::manifest_loader;
use crate::agent::memory_loader::{DefaultMemoryLoader, ManifestMemoryLoader, MemoryLoader};
use crate::agent::prompt::{PromptContext, SystemPromptBuilder};
use crate::config::Config;
use crate::i18n::ToolDescriptions;
use crate::memory::{self, Memory, MemoryCategory};
use crate::observability::{self, Observer, ObserverEvent};
use crate::providers::{self, ChatMessage, Provider};
use crate::runtime;
use crate::security::SecurityPolicy;
use crate::tools::{self, Tool, ToolSpec};
use anyhow::Result;
use std::collections::HashMap;
use std::fmt::Write as FmtWrite;
use std::path::Path;
use std::sync::Arc;
use std::time::Instant;

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub enum ToolDispatchMode {
    #[default]
    Auto,
    Native,
    Xml,
}

impl ToolDispatchMode {
    pub fn from_config_value(value: &str) -> Self {
        match value {
            "native" => Self::Native,
            "xml" => Self::Xml,
            _ => Self::Auto,
        }
    }

    pub fn uses_native_tools(self, provider_supports_native_tools: bool, has_tools: bool) -> bool {
        if !has_tools {
            return false;
        }

        match self {
            Self::Auto => provider_supports_native_tools,
            Self::Native => true,
            Self::Xml => false,
        }
    }
}

pub struct Agent {
    provider: Box<dyn Provider>,
    provider_name: String,
    toolbox_manager: tools::ToolboxManager,
    memory: Arc<dyn Memory>,
    observer: Arc<dyn Observer>,
    prompt_builder: SystemPromptBuilder,
    tool_dispatch_mode: ToolDispatchMode,
    memory_loader: Box<dyn MemoryLoader>,
    config: crate::config::AgentConfig,
    multimodal_config: crate::config::MultimodalConfig,
    pacing: crate::config::PacingConfig,
    model_name: String,
    temperature: f64,
    workspace_dir: std::path::PathBuf,
    identity_config: crate::config::IdentityConfig,
    skills: Vec<crate::skills::Skill>,
    skills_prompt_mode: crate::config::SkillsPromptInjectionMode,
    auto_save: bool,
    memory_session_id: Option<String>,
    history: Vec<ChatMessage>,
    classification_config: crate::config::QueryClassificationConfig,
    available_hints: Vec<String>,
    route_model_by_hint: HashMap<String, String>,
    response_cache: Option<Arc<crate::memory::response_cache::ResponseCache>>,
    tool_descriptions: Option<ToolDescriptions>,
    /// Pre-rendered security policy summary injected into the system prompt
    /// so the LLM knows the concrete constraints before making tool calls.
    security_summary: Option<String>,
    /// Autonomy level from config; controls safety prompt instructions.
    autonomy_level: crate::security::AutonomyLevel,
    manifest: Option<AgentManifest>,
}

struct AgentPromptState<'a> {
    prompt_builder: &'a SystemPromptBuilder,
    toolbox_manager: &'a tools::ToolboxManager,
    workspace_dir: &'a Path,
    model_name: &'a str,
    skills: &'a [crate::skills::Skill],
    skills_prompt_mode: crate::config::SkillsPromptInjectionMode,
    identity_config: &'a crate::config::IdentityConfig,
    tool_descriptions: Option<&'a ToolDescriptions>,
    security_summary: Option<&'a str>,
    autonomy_level: crate::security::AutonomyLevel,
    manifest: Option<&'a AgentManifest>,
    tool_dispatch_mode: ToolDispatchMode,
    provider_supports_native_tools: bool,
}

fn load_agent_manifest(workspace_dir: &Path) -> Result<Option<AgentManifest>> {
    let manifest_path = workspace_dir.join("agent_manifest.toml");
    if !manifest_path.exists() {
        return Ok(None);
    }
    Ok(Some(manifest_loader::load_manifest(&manifest_path)?))
}

pub struct AgentBuilder {
    provider: Option<Box<dyn Provider>>,
    provider_name: Option<String>,
    tools: Option<Vec<Box<dyn Tool>>>,
    toolbox_manager: Option<tools::ToolboxManager>,
    memory: Option<Arc<dyn Memory>>,
    observer: Option<Arc<dyn Observer>>,
    prompt_builder: Option<SystemPromptBuilder>,
    tool_dispatch_mode: Option<ToolDispatchMode>,
    memory_loader: Option<Box<dyn MemoryLoader>>,
    config: Option<crate::config::AgentConfig>,
    multimodal_config: Option<crate::config::MultimodalConfig>,
    pacing: Option<crate::config::PacingConfig>,
    model_name: Option<String>,
    temperature: Option<f64>,
    workspace_dir: Option<std::path::PathBuf>,
    identity_config: Option<crate::config::IdentityConfig>,
    skills: Option<Vec<crate::skills::Skill>>,
    skills_prompt_mode: Option<crate::config::SkillsPromptInjectionMode>,
    auto_save: Option<bool>,
    memory_session_id: Option<String>,
    classification_config: Option<crate::config::QueryClassificationConfig>,
    available_hints: Option<Vec<String>>,
    route_model_by_hint: Option<HashMap<String, String>>,
    allowed_tools: Option<Vec<String>>,
    response_cache: Option<Arc<crate::memory::response_cache::ResponseCache>>,
    tool_descriptions: Option<ToolDescriptions>,
    security_summary: Option<String>,
    autonomy_level: Option<crate::security::AutonomyLevel>,
    manifest: Option<AgentManifest>,
}

impl AgentBuilder {
    pub fn new() -> Self {
        Self {
            provider: None,
            provider_name: None,
            tools: None,
            toolbox_manager: None,
            memory: None,
            observer: None,
            prompt_builder: None,
            tool_dispatch_mode: None,
            memory_loader: None,
            config: None,
            multimodal_config: None,
            pacing: None,
            model_name: None,
            temperature: None,
            workspace_dir: None,
            identity_config: None,
            skills: None,
            skills_prompt_mode: None,
            auto_save: None,
            memory_session_id: None,
            classification_config: None,
            available_hints: None,
            route_model_by_hint: None,
            allowed_tools: None,
            response_cache: None,
            tool_descriptions: None,
            security_summary: None,
            autonomy_level: None,
            manifest: None,
        }
    }

    pub fn provider(mut self, provider: Box<dyn Provider>) -> Self {
        self.provider = Some(provider);
        self
    }

    pub fn provider_name(mut self, provider_name: String) -> Self {
        self.provider_name = Some(provider_name);
        self
    }

    pub fn tools(mut self, tools: Vec<Box<dyn Tool>>) -> Self {
        self.tools = Some(tools);
        self
    }

    pub fn toolbox_manager(mut self, toolbox_manager: tools::ToolboxManager) -> Self {
        self.toolbox_manager = Some(toolbox_manager);
        self
    }

    pub fn memory(mut self, memory: Arc<dyn Memory>) -> Self {
        self.memory = Some(memory);
        self
    }

    pub fn observer(mut self, observer: Arc<dyn Observer>) -> Self {
        self.observer = Some(observer);
        self
    }

    pub fn prompt_builder(mut self, prompt_builder: SystemPromptBuilder) -> Self {
        self.prompt_builder = Some(prompt_builder);
        self
    }

    pub fn tool_dispatch_mode(mut self, tool_dispatch_mode: ToolDispatchMode) -> Self {
        self.tool_dispatch_mode = Some(tool_dispatch_mode);
        self
    }

    pub fn memory_loader(mut self, memory_loader: Box<dyn MemoryLoader>) -> Self {
        self.memory_loader = Some(memory_loader);
        self
    }

    pub fn config(mut self, config: crate::config::AgentConfig) -> Self {
        self.config = Some(config);
        self
    }

    pub fn multimodal_config(mut self, multimodal_config: crate::config::MultimodalConfig) -> Self {
        self.multimodal_config = Some(multimodal_config);
        self
    }

    pub fn pacing(mut self, pacing: crate::config::PacingConfig) -> Self {
        self.pacing = Some(pacing);
        self
    }

    pub fn model_name(mut self, model_name: String) -> Self {
        self.model_name = Some(model_name);
        self
    }

    pub fn temperature(mut self, temperature: f64) -> Self {
        self.temperature = Some(temperature);
        self
    }

    pub fn workspace_dir(mut self, workspace_dir: std::path::PathBuf) -> Self {
        self.workspace_dir = Some(workspace_dir);
        self
    }

    pub fn identity_config(mut self, identity_config: crate::config::IdentityConfig) -> Self {
        self.identity_config = Some(identity_config);
        self
    }

    pub fn skills(mut self, skills: Vec<crate::skills::Skill>) -> Self {
        self.skills = Some(skills);
        self
    }

    pub fn skills_prompt_mode(
        mut self,
        skills_prompt_mode: crate::config::SkillsPromptInjectionMode,
    ) -> Self {
        self.skills_prompt_mode = Some(skills_prompt_mode);
        self
    }

    pub fn auto_save(mut self, auto_save: bool) -> Self {
        self.auto_save = Some(auto_save);
        self
    }

    pub fn memory_session_id(mut self, memory_session_id: Option<String>) -> Self {
        self.memory_session_id = memory_session_id;
        self
    }

    pub fn classification_config(
        mut self,
        classification_config: crate::config::QueryClassificationConfig,
    ) -> Self {
        self.classification_config = Some(classification_config);
        self
    }

    pub fn available_hints(mut self, available_hints: Vec<String>) -> Self {
        self.available_hints = Some(available_hints);
        self
    }

    pub fn route_model_by_hint(mut self, route_model_by_hint: HashMap<String, String>) -> Self {
        self.route_model_by_hint = Some(route_model_by_hint);
        self
    }

    pub fn allowed_tools(mut self, allowed_tools: Option<Vec<String>>) -> Self {
        self.allowed_tools = allowed_tools;
        self
    }

    pub fn response_cache(
        mut self,
        cache: Option<Arc<crate::memory::response_cache::ResponseCache>>,
    ) -> Self {
        self.response_cache = cache;
        self
    }

    pub fn tool_descriptions(mut self, tool_descriptions: Option<ToolDescriptions>) -> Self {
        self.tool_descriptions = tool_descriptions;
        self
    }

    pub fn security_summary(mut self, summary: Option<String>) -> Self {
        self.security_summary = summary;
        self
    }

    pub fn autonomy_level(mut self, level: crate::security::AutonomyLevel) -> Self {
        self.autonomy_level = Some(level);
        self
    }

    pub fn manifest(mut self, manifest: AgentManifest) -> Self {
        self.manifest = Some(manifest);
        self
    }

    pub fn build(self) -> Result<Agent> {
        let manifest_allowed = self
            .manifest
            .as_ref()
            .map(|manifest| manifest.tools.allow.clone());
        let allowed = match (self.allowed_tools.clone(), manifest_allowed) {
            (Some(existing), Some(manifest)) => Some(
                existing
                    .into_iter()
                    .filter(|tool| manifest.iter().any(|allowed| allowed == tool))
                    .collect(),
            ),
            (None, Some(manifest)) => Some(manifest),
            (existing, None) => existing,
        };
        let toolbox_manager = if let Some(toolbox_manager) = self.toolbox_manager {
            toolbox_manager
        } else {
            let mut tools = self
                .tools
                .ok_or_else(|| anyhow::anyhow!("tools are required"))?;
            if let Some(ref allow_list) = allowed {
                tools.retain(|t| allow_list.iter().any(|name| name == t.name()));
            }

            tools::ToolboxManager::from_boxed_tools(
                tools,
                tools::ToolboxAccessConfig {
                    core_tools: self
                        .manifest
                        .as_ref()
                        .map(|manifest| manifest.tools.core_tools.clone())
                        .unwrap_or_default(),
                    discoverable_tools: self
                        .manifest
                        .as_ref()
                        .map(|manifest| manifest.tools.discoverable_tools.clone())
                        .unwrap_or_default(),
                    ..tools::ToolboxAccessConfig::default()
                },
            )
        };
        let discovery_tool: Arc<dyn Tool> =
            Arc::new(tools::ToolDiscoveryTool::new(toolbox_manager.clone()));
        toolbox_manager.register_system_tool(discovery_tool, ["discovery", "system"]);

        let default_memory_loader: Box<dyn MemoryLoader> = if let Some(memory) = self
            .manifest
            .as_ref()
            .and_then(|manifest| manifest.memory.as_ref())
        {
            Box::new(ManifestMemoryLoader::new(
                memory.recall_limit.unwrap_or(5),
                memory.min_relevance_score.unwrap_or(0.4),
                memory.category.clone(),
                memory.session_scope,
            ))
        } else {
            Box::new(DefaultMemoryLoader::default())
        };

        Ok(Agent {
            provider: self
                .provider
                .ok_or_else(|| anyhow::anyhow!("provider is required"))?,
            provider_name: self.provider_name.unwrap_or_else(|| "unknown".into()),
            toolbox_manager,
            memory: self
                .memory
                .ok_or_else(|| anyhow::anyhow!("memory is required"))?,
            observer: self
                .observer
                .ok_or_else(|| anyhow::anyhow!("observer is required"))?,
            prompt_builder: self
                .prompt_builder
                .unwrap_or_else(SystemPromptBuilder::with_defaults),
            tool_dispatch_mode: self.tool_dispatch_mode.unwrap_or_default(),
            memory_loader: self.memory_loader.unwrap_or(default_memory_loader),
            config: self.config.unwrap_or_default(),
            multimodal_config: self.multimodal_config.unwrap_or_default(),
            pacing: self.pacing.unwrap_or_default(),
            model_name: self
                .model_name
                .unwrap_or_else(|| "anthropic/claude-sonnet-4-20250514".into()),
            temperature: self.temperature.unwrap_or(0.7),
            workspace_dir: self
                .workspace_dir
                .unwrap_or_else(|| std::path::PathBuf::from(".")),
            identity_config: self.identity_config.unwrap_or_default(),
            skills: self.skills.unwrap_or_default(),
            skills_prompt_mode: self.skills_prompt_mode.unwrap_or_default(),
            auto_save: self.auto_save.unwrap_or(false),
            memory_session_id: self.memory_session_id,
            history: Vec::new(),
            classification_config: self.classification_config.unwrap_or_default(),
            available_hints: self.available_hints.unwrap_or_default(),
            route_model_by_hint: self.route_model_by_hint.unwrap_or_default(),
            response_cache: self.response_cache,
            tool_descriptions: self.tool_descriptions,
            security_summary: self.security_summary,
            autonomy_level: self
                .autonomy_level
                .unwrap_or(crate::security::AutonomyLevel::Supervised),
            manifest: self.manifest,
        })
    }
}

impl Agent {
    pub fn builder() -> AgentBuilder {
        AgentBuilder::new()
    }

    pub fn history(&self) -> &[ChatMessage] {
        &self.history
    }

    pub fn clear_history(&mut self) {
        self.history.clear();
    }

    pub fn set_memory_session_id(&mut self, session_id: Option<String>) {
        self.memory_session_id = session_id;
    }

    /// Hydrate the agent with prior chat messages (e.g. from a session backend).
    ///
    /// Ensures a system prompt is prepended if history is empty, then appends all
    /// non-system messages from the seed. System messages in the seed are skipped
    /// to avoid duplicating the system prompt.
    pub fn seed_history(&mut self, messages: &[ChatMessage]) {
        if self.history.is_empty() {
            let _ = self.ensure_current_system_prompt();
        }
        for msg in messages {
            if msg.role != "system" {
                self.history.push(msg.clone());
            }
        }
    }

    pub async fn from_config(config: &Config) -> Result<Self> {
        let observer: Arc<dyn Observer> =
            Arc::from(observability::create_observer(&config.observability));
        let runtime: Arc<dyn runtime::RuntimeAdapter> =
            Arc::from(runtime::create_runtime(&config.runtime)?);
        let security = Arc::new(SecurityPolicy::from_config(
            &config.autonomy,
            &config.workspace_dir,
        ));

        let memory: Arc<dyn Memory> = Arc::from(memory::create_memory_with_storage_and_routes(
            &config.memory,
            &config.embedding_routes,
            Some(&config.storage.provider.config),
            &config.workspace_dir,
            config.api_key.as_deref(),
        )?);

        let composio_key = if config.composio.enabled {
            config.composio.api_key.as_deref()
        } else {
            None
        };
        let composio_entity_id = if config.composio.enabled {
            Some(config.composio.entity_id.as_str())
        } else {
            None
        };

        let (mut tools, delegate_handle) = tools::all_tools_with_runtime(
            Arc::new(config.clone()),
            &security,
            runtime,
            memory.clone(),
            composio_key,
            composio_entity_id,
            &config.browser,
            &config.http_request,
            &config.web_fetch,
            &config.workspace_dir,
            &config.agents,
            config.api_key.as_deref(),
            config,
            ModelSwitchState::default(),
        );

        let manifest = load_agent_manifest(&config.workspace_dir)?;
        if let Some(agent_manifest) = manifest.as_ref() {
            if !agent_manifest.tools.allow.is_empty() {
                tools.retain(|tool| {
                    agent_manifest
                        .tools
                        .allow
                        .iter()
                        .any(|allowed| allowed == tool.name())
                });
            }
        }

        // ── Wire MCP tools (non-fatal) ─────────────────────────────
        // Replicates the same MCP initialization logic used in the CLI
        // and webhook paths (loop_.rs) so that the WebSocket/daemon UI
        // path also has access to MCP tools.
        if config.mcp.enabled && !config.mcp.servers.is_empty() {
            tracing::info!(
                "Initializing MCP client — {} server(s) configured",
                config.mcp.servers.len()
            );
            match tools::McpRegistry::connect_all(&config.mcp.servers).await {
                Ok(registry) => {
                    let registry = std::sync::Arc::new(registry);
                    if config.mcp.deferred_loading {
                        let deferred_set = tools::DeferredMcpToolSet::from_registry(
                            std::sync::Arc::clone(&registry),
                        )
                        .await;
                        tracing::info!(
                            "MCP deferred: {} tool stub(s) from {} server(s)",
                            deferred_set.len(),
                            registry.server_count()
                        );
                        let activated = std::sync::Arc::new(std::sync::Mutex::new(
                            tools::ActivatedToolSet::new(),
                        ));
                        tools.push(Box::new(tools::ToolSearchTool::new(
                            deferred_set,
                            activated,
                        )));
                    } else {
                        let names = registry.tool_names();
                        let mut registered = 0usize;
                        for name in names {
                            if let Some(def) = registry.get_tool_def(&name).await {
                                let wrapper: std::sync::Arc<dyn tools::Tool> =
                                    std::sync::Arc::new(tools::McpToolWrapper::new(
                                        name,
                                        def,
                                        std::sync::Arc::clone(&registry),
                                    ));
                                if let Some(ref handle) = delegate_handle {
                                    handle.write().push(std::sync::Arc::clone(&wrapper));
                                }
                                tools.push(Box::new(tools::ArcToolRef(wrapper)));
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
                    tracing::error!("MCP registry failed to initialize: {e:#}");
                }
            }
        }

        let provider_name = config.default_provider.as_deref().unwrap_or("openrouter");

        let model_name = config
            .default_model
            .as_deref()
            .unwrap_or("anthropic/claude-sonnet-4-20250514")
            .to_string();

        let provider_runtime_options = providers::provider_runtime_options_from_config(config);

        let provider: Box<dyn Provider> = providers::create_routed_provider_with_options(
            provider_name,
            config.api_key.as_deref(),
            config.api_url.as_deref(),
            &config.reliability,
            &config.model_routes,
            &model_name,
            &provider_runtime_options,
        )?;

        let tool_dispatch_mode = ToolDispatchMode::from_config_value(&config.agent.tool_dispatcher);

        let route_model_by_hint: HashMap<String, String> = config
            .model_routes
            .iter()
            .map(|route| (route.hint.clone(), route.model.clone()))
            .collect();
        let available_hints: Vec<String> = route_model_by_hint.keys().cloned().collect();

        let response_cache = if config.memory.response_cache_enabled {
            crate::memory::response_cache::ResponseCache::with_hot_cache(
                &config.workspace_dir,
                config.memory.response_cache_ttl_minutes,
                config.memory.response_cache_max_entries,
                config.memory.response_cache_hot_entries,
            )
            .ok()
            .map(Arc::new)
        } else {
            None
        };

        let mut builder = Agent::builder()
            .provider(provider)
            .provider_name(provider_name.to_string())
            .tools(tools)
            .memory(memory)
            .observer(observer)
            .response_cache(response_cache)
            .tool_dispatch_mode(tool_dispatch_mode)
            .memory_loader(Box::new(DefaultMemoryLoader::new(
                5,
                config.memory.min_relevance_score,
            )))
            .prompt_builder(SystemPromptBuilder::with_defaults())
            .config(config.agent.clone())
            .multimodal_config(config.multimodal.clone())
            .pacing(config.pacing.clone())
            .model_name(model_name)
            .temperature(config.default_temperature)
            .workspace_dir(config.workspace_dir.clone())
            .classification_config(config.query_classification.clone())
            .available_hints(available_hints)
            .route_model_by_hint(route_model_by_hint)
            .identity_config(config.identity.clone())
            .skills(crate::skills::load_skills_with_config(
                &config.workspace_dir,
                config,
            ))
            .skills_prompt_mode(config.skills.prompt_injection_mode)
            .auto_save(config.memory.auto_save)
            .security_summary(Some(security.prompt_summary()))
            .autonomy_level(config.autonomy.level);
        if let Some(agent_manifest) = manifest.clone() {
            builder = builder.manifest(agent_manifest);
        }
        builder.build()
    }

    fn trim_history(&mut self) {
        trim_chat_history(&mut self.history, self.config.max_history_messages);
    }

    fn build_system_prompt_for_state(state: AgentPromptState<'_>) -> Result<String> {
        let active_tools = state.toolbox_manager.active_tools_boxed();
        let tool_specs = state.toolbox_manager.active_tool_specs();
        let use_native_tools = state
            .tool_dispatch_mode
            .uses_native_tools(state.provider_supports_native_tools, !tool_specs.is_empty());
        let instructions = if use_native_tools {
            String::new()
        } else {
            build_tool_instructions_from_specs(&tool_specs, state.tool_descriptions)
        };
        let ctx = PromptContext {
            workspace_dir: state.workspace_dir,
            model_name: state.model_name,
            tools: &active_tools,
            skills: state.skills,
            skills_prompt_mode: state.skills_prompt_mode,
            identity_config: Some(state.identity_config),
            manifest_identity_prompt: state
                .manifest
                .and_then(|value| value.identity.system_prompt.as_deref()),
            dispatcher_instructions: &instructions,
            tool_descriptions: state.tool_descriptions,
            security_summary: state.security_summary.map(str::to_string),
            autonomy_level: state.autonomy_level,
        };
        let mut prompt = state.prompt_builder.build(&ctx)?;
        let discovery_section = state.toolbox_manager.discovery_prompt_section();
        if !discovery_section.is_empty() {
            prompt.push('\n');
            prompt.push('\n');
            prompt.push_str(discovery_section.trim_end());
        }
        if let Some(manifest) = state.manifest {
            prompt.push_str("\n\n## Agent Manifest Identity\n\n");
            let name = manifest.identity.name.as_deref().unwrap_or("Unnamed agent");
            let role = manifest.identity.role.as_deref().unwrap_or("unspecified");
            let system_prompt = manifest
                .identity
                .system_prompt
                .as_deref()
                .unwrap_or("No manifest system prompt provided.");
            let _ = write!(
                prompt,
                "- Agent: {}\n- Role: {}\n\n{}",
                name, role, system_prompt
            );
        }
        Ok(prompt)
    }

    fn build_system_prompt(&self) -> Result<String> {
        Self::build_system_prompt_for_state(AgentPromptState {
            prompt_builder: &self.prompt_builder,
            toolbox_manager: &self.toolbox_manager,
            workspace_dir: &self.workspace_dir,
            model_name: &self.model_name,
            skills: &self.skills,
            skills_prompt_mode: self.skills_prompt_mode,
            identity_config: &self.identity_config,
            tool_descriptions: self.tool_descriptions.as_ref(),
            security_summary: self.security_summary.as_deref(),
            autonomy_level: self.autonomy_level,
            manifest: self.manifest.as_ref(),
            tool_dispatch_mode: self.tool_dispatch_mode,
            provider_supports_native_tools: self.provider.supports_native_tools(),
        })
    }

    fn ensure_current_system_prompt(&mut self) -> Result<()> {
        let system_prompt = self.build_system_prompt()?;
        match self.history.first_mut() {
            Some(chat) if chat.role == "system" => chat.content = system_prompt,
            _ => self.history.insert(0, ChatMessage::system(system_prompt)),
        }
        Ok(())
    }

    fn current_tool_specs(&self) -> Vec<ToolSpec> {
        self.toolbox_manager.active_tool_specs()
    }

    fn classify_model(&self, user_message: &str) -> String {
        if let Some(decision) =
            super::classifier::classify_with_decision(&self.classification_config, user_message)
        {
            if self.available_hints.contains(&decision.hint) {
                let resolved_model = self
                    .route_model_by_hint
                    .get(&decision.hint)
                    .map(String::as_str)
                    .unwrap_or("unknown");
                tracing::info!(
                    target: "query_classification",
                    hint = decision.hint.as_str(),
                    model = resolved_model,
                    rule_priority = decision.priority,
                    message_length = user_message.len(),
                    "Classified message route"
                );
                return format!("hint:{}", decision.hint);
            }
        }
        self.model_name.clone()
    }

    pub async fn turn(&mut self, user_message: &str) -> Result<String> {
        if self.history.is_empty() {
            self.ensure_current_system_prompt()?;
        }

        let context = self
            .memory_loader
            .load_context(
                self.memory.as_ref(),
                user_message,
                self.memory_session_id.as_deref(),
            )
            .await
            .unwrap_or_default();

        if self.auto_save {
            let _ = self
                .memory
                .store(
                    "user_msg",
                    user_message,
                    MemoryCategory::Conversation,
                    self.memory_session_id.as_deref(),
                )
                .await;
        }

        let now = chrono::Local::now().format("%Y-%m-%d %H:%M:%S %Z");
        let enriched = if context.is_empty() {
            format!("[{now}] {user_message}")
        } else {
            format!("{context}[{now}] {user_message}")
        };

        self.history.push(ChatMessage::user(enriched));

        let effective_model = self.classify_model(user_message);
        let cache_key = if self.temperature == 0.0 {
            self.response_cache.as_ref().map(|_| {
                let last_user = self
                    .history
                    .iter()
                    .rfind(|m| m.role == "user")
                    .map(|m| m.content.as_str())
                    .unwrap_or("");
                let system = self
                    .history
                    .iter()
                    .find(|m| m.role == "system")
                    .map(|m| m.content.as_str());
                crate::memory::response_cache::ResponseCache::cache_key(
                    &effective_model,
                    system,
                    last_user,
                )
            })
        } else {
            None
        };

        if let (Some(cache), Some(key)) = (&self.response_cache, &cache_key) {
            if let Ok(Some(cached)) = cache.get(key) {
                self.observer.record_event(&ObserverEvent::CacheHit {
                    cache_type: "response".into(),
                    tokens_saved: 0,
                });
                self.history.push(ChatMessage::assistant(cached.clone()));
                self.trim_history();
                return Ok(cached);
            }
            self.observer.record_event(&ObserverEvent::CacheMiss {
                cache_type: "response".into(),
            });
        }

        self.ensure_current_system_prompt()?;

        let prompt_builder = &self.prompt_builder;
        let toolbox_manager = &self.toolbox_manager;
        let workspace_dir = self.workspace_dir.clone();
        let model_name = self.model_name.clone();
        let skills = &self.skills;
        let skills_prompt_mode = self.skills_prompt_mode;
        let identity_config = &self.identity_config;
        let tool_descriptions = self.tool_descriptions.as_ref();
        let security_summary = self.security_summary.clone();
        let autonomy_level = self.autonomy_level;
        let manifest = self.manifest.as_ref();
        let tool_dispatch_mode = self.tool_dispatch_mode;
        let provider_supports_native_tools = self.provider.supports_native_tools();
        let prompt_renderer = || {
            Self::build_system_prompt_for_state(AgentPromptState {
                prompt_builder,
                toolbox_manager,
                workspace_dir: &workspace_dir,
                model_name: &model_name,
                skills,
                skills_prompt_mode,
                identity_config,
                tool_descriptions,
                security_summary: security_summary.as_deref(),
                autonomy_level,
                manifest,
                tool_dispatch_mode,
                provider_supports_native_tools,
            })
            .unwrap_or_else(|err| {
                tracing::error!(error = %err, "Failed to build agent system prompt");
                String::new()
            })
        };
        let empty_tools: &[Box<dyn Tool>] = &[];
        let dedup_exempt_tools = self.config.tool_call_dedup_exempt.clone();
        let history_len_before_loop = self.history.len();
        let response = run_tool_call_loop_with_policy(
            self.provider.as_ref(),
            &mut self.history,
            empty_tools,
            Some(&self.toolbox_manager),
            self.observer.as_ref(),
            &self.provider_name,
            &effective_model,
            self.temperature,
            false,
            None,
            "agent",
            None,
            &self.multimodal_config,
            self.config.max_tool_iterations,
            None,
            None,
            None,
            &[],
            &dedup_exempt_tools,
            None,
            None,
            Some(&prompt_renderer),
            &self.pacing,
            self.config.parallel_tools,
            self.tool_dispatch_mode,
        )
        .await?;

        let used_tools = self.history[history_len_before_loop..].iter().any(|msg| {
            msg.role == "tool"
                || (msg.role == "user" && msg.content.starts_with("[Tool results]\n"))
        });

        if !used_tools {
            if let (Some(cache), Some(key)) = (&self.response_cache, &cache_key) {
                let _ = cache.put(key, &effective_model, &response, 0);
            }
        }

        self.trim_history();
        Ok(response)
    }

    pub async fn run_single(&mut self, message: &str) -> Result<String> {
        self.turn(message).await
    }

    pub async fn run_interactive(&mut self) -> Result<()> {
        println!("🦀 R.A.I.N. Interactive Mode");
        println!("Type /quit to exit.\n");

        let (tx, mut rx) = tokio::sync::mpsc::channel(32);
        let cli = crate::channels::CliChannel::new();

        let listen_handle = tokio::spawn(async move {
            let _ = crate::channels::Channel::listen(&cli, tx).await;
        });

        while let Some(msg) = rx.recv().await {
            let response = match self.turn(&msg.content).await {
                Ok(resp) => resp,
                Err(e) => {
                    eprintln!("\nError: {e}\n");
                    continue;
                }
            };
            println!("\n{response}\n");
        }

        listen_handle.abort();
        Ok(())
    }
}

pub async fn run(
    config: Config,
    message: Option<String>,
    provider_override: Option<String>,
    model_override: Option<String>,
    temperature: f64,
) -> Result<()> {
    let start = Instant::now();

    let mut effective_config = config;
    if let Some(p) = provider_override {
        effective_config.default_provider = Some(p);
    }
    if let Some(m) = model_override {
        effective_config.default_model = Some(m);
    }
    effective_config.default_temperature = temperature;

    let mut agent = Agent::from_config(&effective_config).await?;

    let provider_name = effective_config
        .default_provider
        .as_deref()
        .unwrap_or("openrouter")
        .to_string();
    let model_name = effective_config
        .default_model
        .as_deref()
        .unwrap_or("anthropic/claude-sonnet-4-20250514")
        .to_string();

    agent.observer.record_event(&ObserverEvent::AgentStart {
        provider: provider_name.clone(),
        model: model_name.clone(),
    });

    if let Some(msg) = message {
        let response = agent.run_single(&msg).await?;
        println!("{response}");
    } else {
        agent.run_interactive().await?;
    }

    agent.observer.record_event(&ObserverEvent::AgentEnd {
        provider: provider_name,
        model: model_name,
        duration: start.elapsed(),
        tokens_used: None,
        cost_usd: None,
    });

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::providers::ChatRequest;
    use async_trait::async_trait;
    use parking_lot::Mutex;
    use std::collections::HashMap;
    use tempfile::tempdir;

    struct MockProvider {
        responses: Mutex<Vec<crate::providers::ChatResponse>>,
    }

    #[async_trait]
    impl Provider for MockProvider {
        async fn chat_with_system(
            &self,
            _system_prompt: Option<&str>,
            _message: &str,
            _model: &str,
            _temperature: f64,
        ) -> Result<String> {
            Ok("ok".into())
        }

        async fn chat(
            &self,
            _request: ChatRequest<'_>,
            _model: &str,
            _temperature: f64,
        ) -> Result<crate::providers::ChatResponse> {
            let mut guard = self.responses.lock();
            if guard.is_empty() {
                return Ok(crate::providers::ChatResponse {
                    text: Some("done".into()),
                    tool_calls: vec![],
                    usage: None,
                    reasoning_content: None,
                });
            }
            Ok(guard.remove(0))
        }
    }

    struct ModelCaptureProvider {
        responses: Mutex<Vec<crate::providers::ChatResponse>>,
        seen_models: Arc<Mutex<Vec<String>>>,
    }

    #[async_trait]
    impl Provider for ModelCaptureProvider {
        async fn chat_with_system(
            &self,
            _system_prompt: Option<&str>,
            _message: &str,
            _model: &str,
            _temperature: f64,
        ) -> Result<String> {
            Ok("ok".into())
        }

        async fn chat(
            &self,
            _request: ChatRequest<'_>,
            model: &str,
            _temperature: f64,
        ) -> Result<crate::providers::ChatResponse> {
            self.seen_models.lock().push(model.to_string());
            let mut guard = self.responses.lock();
            if guard.is_empty() {
                return Ok(crate::providers::ChatResponse {
                    text: Some("done".into()),
                    tool_calls: vec![],
                    usage: None,
                    reasoning_content: None,
                });
            }
            Ok(guard.remove(0))
        }
    }

    struct ToolSpecCaptureProvider {
        responses: Mutex<Vec<crate::providers::ChatResponse>>,
        seen_tool_specs: Arc<Mutex<Vec<Vec<String>>>>,
    }

    #[async_trait]
    impl Provider for ToolSpecCaptureProvider {
        async fn chat_with_system(
            &self,
            _system_prompt: Option<&str>,
            _message: &str,
            _model: &str,
            _temperature: f64,
        ) -> Result<String> {
            Ok("ok".into())
        }

        async fn chat(
            &self,
            request: ChatRequest<'_>,
            _model: &str,
            _temperature: f64,
        ) -> Result<crate::providers::ChatResponse> {
            self.seen_tool_specs.lock().push(
                request
                    .tools
                    .unwrap_or(&[])
                    .iter()
                    .map(|spec| spec.name.clone())
                    .collect(),
            );
            let mut guard = self.responses.lock();
            if guard.is_empty() {
                return Ok(crate::providers::ChatResponse {
                    text: Some("done".into()),
                    tool_calls: vec![],
                    usage: None,
                    reasoning_content: None,
                });
            }
            Ok(guard.remove(0))
        }
    }

    struct MockTool;
    struct MockOtherTool;

    #[async_trait]
    impl Tool for MockTool {
        fn name(&self) -> &str {
            "echo"
        }

        fn description(&self) -> &str {
            "echo"
        }

        fn parameters_schema(&self) -> serde_json::Value {
            serde_json::json!({"type": "object"})
        }

        async fn execute(&self, _args: serde_json::Value) -> Result<crate::tools::ToolResult> {
            Ok(crate::tools::ToolResult {
                success: true,
                output: "tool-out".into(),
                error: None,
            })
        }
    }

    #[async_trait]
    impl Tool for MockOtherTool {
        fn name(&self) -> &str {
            "file_list"
        }

        fn description(&self) -> &str {
            "file_list"
        }

        fn parameters_schema(&self) -> serde_json::Value {
            serde_json::json!({"type": "object"})
        }

        async fn execute(&self, _args: serde_json::Value) -> Result<crate::tools::ToolResult> {
            Ok(crate::tools::ToolResult {
                success: true,
                output: "files".into(),
                error: None,
            })
        }
    }

    #[tokio::test]
    async fn turn_without_tools_returns_text() {
        let provider = Box::new(MockProvider {
            responses: Mutex::new(vec![crate::providers::ChatResponse {
                text: Some("hello".into()),
                tool_calls: vec![],
                usage: None,
                reasoning_content: None,
            }]),
        });

        let memory_cfg = crate::config::MemoryConfig {
            backend: "none".into(),
            ..crate::config::MemoryConfig::default()
        };
        let mem: Arc<dyn Memory> = Arc::from(
            crate::memory::create_memory(&memory_cfg, std::path::Path::new("/tmp"), None)
                .expect("memory creation should succeed with valid config"),
        );

        let observer: Arc<dyn Observer> = Arc::from(crate::observability::NoopObserver {});
        let mut agent = Agent::builder()
            .provider(provider)
            .tools(vec![Box::new(MockTool)])
            .memory(mem)
            .observer(observer)
            .tool_dispatch_mode(ToolDispatchMode::Xml)
            .workspace_dir(std::path::PathBuf::from("/tmp"))
            .build()
            .expect("agent builder should succeed with valid config");

        let response = agent.turn("hi").await.unwrap();
        assert_eq!(response, "hello");
    }

    #[tokio::test]
    async fn turn_with_native_dispatcher_handles_tool_results_variant() {
        let provider = Box::new(MockProvider {
            responses: Mutex::new(vec![
                crate::providers::ChatResponse {
                    text: Some(String::new()),
                    tool_calls: vec![crate::providers::ToolCall {
                        id: "tc1".into(),
                        name: "echo".into(),
                        arguments: "{}".into(),
                    }],
                    usage: None,
                    reasoning_content: None,
                },
                crate::providers::ChatResponse {
                    text: Some("done".into()),
                    tool_calls: vec![],
                    usage: None,
                    reasoning_content: None,
                },
            ]),
        });

        let memory_cfg = crate::config::MemoryConfig {
            backend: "none".into(),
            ..crate::config::MemoryConfig::default()
        };
        let mem: Arc<dyn Memory> = Arc::from(
            crate::memory::create_memory(&memory_cfg, std::path::Path::new("/tmp"), None)
                .expect("memory creation should succeed with valid config"),
        );

        let observer: Arc<dyn Observer> = Arc::from(crate::observability::NoopObserver {});
        let mut agent = Agent::builder()
            .provider(provider)
            .tools(vec![Box::new(MockTool)])
            .memory(mem)
            .observer(observer)
            .tool_dispatch_mode(ToolDispatchMode::Native)
            .workspace_dir(std::path::PathBuf::from("/tmp"))
            .build()
            .expect("agent builder should succeed with valid config");

        let response = agent.turn("hi").await.unwrap();
        assert_eq!(response, "done");
        assert!(agent.history().iter().any(|msg| msg.role == "tool"));
    }

    #[tokio::test]
    async fn tool_discovery_activation_refreshes_visible_tool_specs() {
        let seen_tool_specs = Arc::new(Mutex::new(Vec::new()));
        let provider = Box::new(ToolSpecCaptureProvider {
            responses: Mutex::new(vec![
                crate::providers::ChatResponse {
                    text: Some(String::new()),
                    tool_calls: vec![crate::providers::ToolCall {
                        id: "tc1".into(),
                        name: "tool_discovery".into(),
                        arguments: r#"{"action":"activate","tool_name":"echo"}"#.into(),
                    }],
                    usage: None,
                    reasoning_content: None,
                },
                crate::providers::ChatResponse {
                    text: Some("activated".into()),
                    tool_calls: vec![],
                    usage: None,
                    reasoning_content: None,
                },
            ]),
            seen_tool_specs: Arc::clone(&seen_tool_specs),
        });

        let memory_cfg = crate::config::MemoryConfig {
            backend: "none".into(),
            ..crate::config::MemoryConfig::default()
        };
        let mem: Arc<dyn Memory> = Arc::from(
            crate::memory::create_memory(&memory_cfg, std::path::Path::new("/tmp"), None)
                .expect("memory creation should succeed with valid config"),
        );
        let observer: Arc<dyn Observer> = Arc::from(crate::observability::NoopObserver {});
        let manifest = crate::agent::manifest::AgentManifest {
            schema_version: "1".into(),
            identity: crate::agent::manifest::IdentitySection::default(),
            tools: crate::agent::manifest::ToolScope {
                allow: vec!["echo".into()],
                deny: vec![],
                core_tools: vec![],
                discoverable_tools: vec!["echo".into()],
                session_scope: crate::agent::manifest::SessionScope::Current,
            },
            memory: None,
            rag: None,
            orchestration: None,
            provider_defaults: None,
        };

        let mut agent = Agent::builder()
            .provider(provider)
            .tools(vec![Box::new(MockTool)])
            .memory(mem)
            .observer(observer)
            .tool_dispatch_mode(ToolDispatchMode::Native)
            .workspace_dir(std::path::PathBuf::from("/tmp"))
            .manifest(manifest)
            .build()
            .expect("agent builder should succeed with valid config");

        let response = agent.turn("load the tool when needed").await.unwrap();
        assert_eq!(response, "activated");

        let seen = seen_tool_specs.lock();
        assert_eq!(seen.len(), 2);
        assert_eq!(seen[0], vec!["tool_discovery".to_string()]);
        assert_eq!(
            seen[1],
            vec!["echo".to_string(), "tool_discovery".to_string()]
        );
    }

    #[tokio::test]
    async fn turn_routes_with_hint_when_query_classification_matches() {
        let seen_models = Arc::new(Mutex::new(Vec::new()));
        let provider = Box::new(ModelCaptureProvider {
            responses: Mutex::new(vec![crate::providers::ChatResponse {
                text: Some("classified".into()),
                tool_calls: vec![],
                usage: None,
                reasoning_content: None,
            }]),
            seen_models: seen_models.clone(),
        });

        let memory_cfg = crate::config::MemoryConfig {
            backend: "none".into(),
            ..crate::config::MemoryConfig::default()
        };
        let mem: Arc<dyn Memory> = Arc::from(
            crate::memory::create_memory(&memory_cfg, std::path::Path::new("/tmp"), None)
                .expect("memory creation should succeed with valid config"),
        );

        let observer: Arc<dyn Observer> = Arc::from(crate::observability::NoopObserver {});
        let mut route_model_by_hint = HashMap::new();
        route_model_by_hint.insert("fast".to_string(), "anthropic/claude-haiku-4-5".to_string());
        let mut agent = Agent::builder()
            .provider(provider)
            .tools(vec![Box::new(MockTool)])
            .memory(mem)
            .observer(observer)
            .tool_dispatch_mode(ToolDispatchMode::Native)
            .workspace_dir(std::path::PathBuf::from("/tmp"))
            .classification_config(crate::config::QueryClassificationConfig {
                enabled: true,
                rules: vec![crate::config::ClassificationRule {
                    hint: "fast".to_string(),
                    keywords: vec!["quick".to_string()],
                    patterns: vec![],
                    min_length: None,
                    max_length: None,
                    priority: 10,
                }],
            })
            .available_hints(vec!["fast".to_string()])
            .route_model_by_hint(route_model_by_hint)
            .build()
            .expect("agent builder should succeed with valid config");

        let response = agent.turn("quick summary please").await.unwrap();
        assert_eq!(response, "classified");
        let seen = seen_models.lock();
        assert_eq!(seen.as_slice(), &["hint:fast".to_string()]);
    }

    #[tokio::test]
    async fn from_config_passes_extra_headers_to_custom_provider() {
        use axum::{Json, Router, http::HeaderMap, routing::post};
        use tempfile::TempDir;
        use tokio::net::TcpListener;

        let captured_headers: Arc<std::sync::Mutex<Option<HashMap<String, String>>>> =
            Arc::new(std::sync::Mutex::new(None));
        let captured_headers_clone = captured_headers.clone();

        let app = Router::new().route(
            "/chat/completions",
            post(
                move |headers: HeaderMap, Json(_body): Json<serde_json::Value>| {
                    let captured_headers = captured_headers_clone.clone();
                    async move {
                        let collected = headers
                            .iter()
                            .filter_map(|(name, value)| {
                                value
                                    .to_str()
                                    .ok()
                                    .map(|value| (name.as_str().to_string(), value.to_string()))
                            })
                            .collect();
                        *captured_headers.lock().unwrap() = Some(collected);
                        Json(serde_json::json!({
                            "choices": [{
                                "message": {
                                    "content": "hello from mock"
                                }
                            }]
                        }))
                    }
                },
            ),
        );

        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let server_handle = tokio::spawn(async move {
            axum::serve(listener, app).await.unwrap();
        });

        let tmp = TempDir::new().expect("temp dir");
        let workspace_dir = tmp.path().join("workspace");
        std::fs::create_dir_all(&workspace_dir).unwrap();

        let mut config = crate::config::Config::default();
        config.workspace_dir = workspace_dir;
        config.config_path = tmp.path().join("config.toml");
        config.api_key = Some("test-key".to_string());
        config.default_provider = Some(format!("custom:http://{addr}"));
        config.default_model = Some("test-model".to_string());
        config.memory.backend = "none".to_string();
        config.memory.auto_save = false;
        config.extra_headers.insert(
            "User-Agent".to_string(),
            "R.A.I.N.-web-test/1.0".to_string(),
        );
        config
            .extra_headers
            .insert("X-Title".to_string(), "R.A.I.N.-web".to_string());

        let mut agent = Agent::from_config(&config)
            .await
            .expect("agent from config");
        let response = agent.turn("hello").await.expect("agent turn");

        assert_eq!(response, "hello from mock");

        let headers = captured_headers
            .lock()
            .unwrap()
            .clone()
            .expect("captured headers");
        assert_eq!(
            headers.get("user-agent").map(String::as_str),
            Some("R.A.I.N.-web-test/1.0")
        );
        assert_eq!(
            headers.get("x-title").map(String::as_str),
            Some("R.A.I.N.-web")
        );

        server_handle.abort();
    }

    #[test]
    fn builder_allowed_tools_none_keeps_all_tools() {
        let provider = Box::new(MockProvider {
            responses: Mutex::new(vec![]),
        });

        let memory_cfg = crate::config::MemoryConfig {
            backend: "none".into(),
            ..crate::config::MemoryConfig::default()
        };
        let mem: Arc<dyn Memory> = Arc::from(
            crate::memory::create_memory(&memory_cfg, std::path::Path::new("/tmp"), None)
                .expect("memory creation should succeed with valid config"),
        );

        let observer: Arc<dyn Observer> = Arc::from(crate::observability::NoopObserver {});
        let agent = Agent::builder()
            .provider(provider)
            .tools(vec![Box::new(MockTool)])
            .memory(mem)
            .observer(observer)
            .tool_dispatch_mode(ToolDispatchMode::Native)
            .workspace_dir(std::path::PathBuf::from("/tmp"))
            .allowed_tools(None)
            .build()
            .expect("agent builder should succeed with valid config");

        let tool_specs = agent.current_tool_specs();
        assert_eq!(tool_specs.len(), 2);
        assert_eq!(tool_specs[0].name, "echo");
        assert_eq!(tool_specs[1].name, "tool_discovery");
    }

    #[test]
    fn builder_allowed_tools_some_filters_tools() {
        let provider = Box::new(MockProvider {
            responses: Mutex::new(vec![]),
        });

        let memory_cfg = crate::config::MemoryConfig {
            backend: "none".into(),
            ..crate::config::MemoryConfig::default()
        };
        let mem: Arc<dyn Memory> = Arc::from(
            crate::memory::create_memory(&memory_cfg, std::path::Path::new("/tmp"), None)
                .expect("memory creation should succeed with valid config"),
        );

        let observer: Arc<dyn Observer> = Arc::from(crate::observability::NoopObserver {});
        let agent = Agent::builder()
            .provider(provider)
            .tools(vec![Box::new(MockTool)])
            .memory(mem)
            .observer(observer)
            .tool_dispatch_mode(ToolDispatchMode::Native)
            .workspace_dir(std::path::PathBuf::from("/tmp"))
            .allowed_tools(Some(vec!["nonexistent".to_string()]))
            .build()
            .expect("agent builder should succeed with valid config");

        let tool_specs = agent.current_tool_specs();
        assert_eq!(tool_specs.len(), 1);
        assert_eq!(tool_specs[0].name, "tool_discovery");
    }

    #[test]
    fn builder_manifest_allowlist_is_narrowing_gate() {
        let provider = Box::new(MockProvider {
            responses: Mutex::new(vec![]),
        });

        let memory_cfg = crate::config::MemoryConfig {
            backend: "none".into(),
            ..crate::config::MemoryConfig::default()
        };
        let mem: Arc<dyn Memory> = Arc::from(
            crate::memory::create_memory(&memory_cfg, std::path::Path::new("/tmp"), None)
                .expect("memory creation should succeed with valid config"),
        );
        let observer: Arc<dyn Observer> = Arc::from(crate::observability::NoopObserver {});
        let manifest = crate::agent::manifest::AgentManifest {
            schema_version: "1".into(),
            identity: crate::agent::manifest::IdentitySection::default(),
            tools: crate::agent::manifest::ToolScope {
                allow: vec!["echo".into()],
                deny: vec![],
                core_tools: vec![],
                discoverable_tools: vec![],
                session_scope: crate::agent::manifest::SessionScope::Current,
            },
            memory: None,
            rag: None,
            orchestration: None,
            provider_defaults: None,
        };

        let agent = Agent::builder()
            .provider(provider)
            .tools(vec![Box::new(MockTool), Box::new(MockOtherTool)])
            .memory(mem)
            .observer(observer)
            .tool_dispatch_mode(ToolDispatchMode::Native)
            .workspace_dir(std::path::PathBuf::from("/tmp"))
            .allowed_tools(Some(vec!["echo".to_string(), "file_list".to_string()]))
            .manifest(manifest)
            .build()
            .expect("agent builder should succeed with valid config");

        let tool_specs = agent.current_tool_specs();
        assert_eq!(tool_specs.len(), 2);
        assert_eq!(tool_specs[0].name, "echo");
        assert_eq!(tool_specs[1].name, "tool_discovery");
    }

    #[test]
    fn builder_system_prompt_prefers_manifest_identity_prompt() {
        let provider = Box::new(MockProvider {
            responses: Mutex::new(vec![]),
        });

        let memory_cfg = crate::config::MemoryConfig {
            backend: "none".into(),
            ..crate::config::MemoryConfig::default()
        };
        let mem: Arc<dyn Memory> = Arc::from(
            crate::memory::create_memory(&memory_cfg, std::path::Path::new("/tmp"), None)
                .expect("memory creation should succeed with valid config"),
        );
        let observer: Arc<dyn Observer> = Arc::from(crate::observability::NoopObserver {});
        let manifest = crate::agent::manifest::AgentManifest {
            schema_version: "1".into(),
            identity: crate::agent::manifest::IdentitySection {
                name: None,
                role: None,
                system_prompt: Some("Manifest identity comes first.".into()),
            },
            tools: crate::agent::manifest::ToolScope {
                allow: vec!["echo".into()],
                deny: vec![],
                core_tools: vec![],
                discoverable_tools: vec![],
                session_scope: crate::agent::manifest::SessionScope::Current,
            },
            memory: None,
            rag: None,
            orchestration: None,
            provider_defaults: None,
        };

        let temp = tempfile::tempdir().unwrap();
        let workspace = temp.path().join("workspace");
        std::fs::create_dir_all(&workspace).unwrap();
        std::fs::write(workspace.join("AGENTS.md"), "Workspace fallback identity").unwrap();

        let agent = Agent::builder()
            .provider(provider)
            .tools(vec![Box::new(MockTool)])
            .memory(mem)
            .observer(observer)
            .tool_dispatch_mode(ToolDispatchMode::Native)
            .workspace_dir(workspace)
            .manifest(manifest)
            .build()
            .expect("agent builder should succeed with valid config");

        let prompt = agent.build_system_prompt().unwrap();
        let manifest_pos = prompt.find("Manifest identity comes first.").unwrap();
        let fallback_pos = prompt.find("Workspace fallback identity").unwrap();
        assert!(manifest_pos < fallback_pos);
    }

    #[test]
    fn seed_history_prepends_system_and_skips_system_from_seed() {
        let provider = Box::new(MockProvider {
            responses: Mutex::new(vec![]),
        });

        let memory_cfg = crate::config::MemoryConfig {
            backend: "none".into(),
            ..crate::config::MemoryConfig::default()
        };
        let mem: Arc<dyn Memory> = Arc::from(
            crate::memory::create_memory(&memory_cfg, std::path::Path::new("/tmp"), None)
                .expect("memory creation should succeed with valid config"),
        );

        let observer: Arc<dyn Observer> = Arc::from(crate::observability::NoopObserver {});
        let mut agent = Agent::builder()
            .provider(provider)
            .tools(vec![Box::new(MockTool)])
            .memory(mem)
            .observer(observer)
            .tool_dispatch_mode(ToolDispatchMode::Native)
            .workspace_dir(std::path::PathBuf::from("/tmp"))
            .build()
            .expect("agent builder should succeed with valid config");

        let seed = vec![
            ChatMessage::system("old system prompt"),
            ChatMessage::user("hello"),
            ChatMessage::assistant("hi there"),
        ];
        agent.seed_history(&seed);

        let history = agent.history();
        // First message should be a freshly built system prompt (not the seed one)
        assert_eq!(history[0].role, "system");
        // System message from seed should be skipped, so next is user
        assert_eq!(history[1].role, "user");
        assert_eq!(history[1].content, "hello");
        assert_eq!(history[2].role, "assistant");
        assert_eq!(history[2].content, "hi there");
        assert_eq!(history.len(), 3);
    }

    #[test]
    fn load_agent_manifest_reads_toml_schema() {
        let dir = tempdir().expect("tempdir should be created");
        let manifest = r#"
schema_version = "1.0"

[identity]
name = "R.A.I.N.Agent"
role = "Lead Scientist"
system_prompt = "Focus on resonance."

[tools]
allow = ["file_read", "web_search"]
core_tools = ["file_read"]
discoverable_tools = ["web_search"]

[memory]
recall_limit = 8
min_relevance_score = 0.6
category = "core"
"#;
        std::fs::write(dir.path().join("agent_manifest.toml"), manifest)
            .expect("manifest should be written");

        let parsed = load_agent_manifest(dir.path())
            .expect("manifest should parse")
            .expect("manifest should exist");

        assert_eq!(parsed.identity.name.as_deref(), Some("R.A.I.N.Agent"));
        assert_eq!(parsed.tools.allow, vec!["file_read", "shell"]);
        assert_eq!(parsed.tools.core_tools, vec!["file_read"]);
        assert_eq!(parsed.tools.discoverable_tools, vec!["shell"]);
        let memory = parsed.memory.expect("memory config should be present");
        assert_eq!(memory.recall_limit, Some(8));
        assert_eq!(memory.min_relevance_score, Some(0.6));
        assert_eq!(memory.category, Some(MemoryCategory::Core));
    }
}
