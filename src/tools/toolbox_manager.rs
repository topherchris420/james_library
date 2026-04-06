use super::{ArcToolRef, Tool, ToolSpec};
use crate::agent::tool_call_parser::map_tool_name_alias;
use crate::security::{IamPolicy, NevisIdentity, PolicyDecision};
use anyhow::{Result, bail};
use parking_lot::Mutex;
use serde::Serialize;
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::sync::Arc;

#[derive(Clone, Default)]
pub struct ToolboxAccessConfig {
    pub core_tools: Vec<String>,
    pub discoverable_tools: Vec<String>,
    pub iam_policy: Option<Arc<IamPolicy>>,
    pub iam_identity: Option<NevisIdentity>,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct ToolCatalogEntry {
    pub name: String,
    pub description: String,
    pub categories: Vec<String>,
    pub active: bool,
    pub core: bool,
    pub discoverable: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ToolActivationStatus {
    Activated,
    AlreadyActive,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ToolActivationResult {
    pub status: ToolActivationStatus,
    pub tool: ToolCatalogEntry,
}

#[derive(Clone)]
struct ToolRegistration {
    tool: Arc<dyn Tool>,
    description: String,
    categories: Vec<String>,
}

struct ToolboxState {
    registry: HashMap<String, ToolRegistration>,
    order: Vec<String>,
    active: HashSet<String>,
    core: HashSet<String>,
    discoverable: HashSet<String>,
    iam_policy: Option<Arc<IamPolicy>>,
    iam_identity: Option<NevisIdentity>,
}

#[derive(Clone)]
pub struct ToolboxManager {
    inner: Arc<Mutex<ToolboxState>>,
}

impl ToolboxManager {
    pub fn from_boxed_tools(tools: Vec<Box<dyn Tool>>, config: ToolboxAccessConfig) -> Self {
        let registry = tools
            .into_iter()
            .map(Arc::<dyn Tool>::from)
            .collect::<Vec<_>>();
        Self::from_registry(registry, config)
    }

    pub fn from_registry(tools: Vec<Arc<dyn Tool>>, config: ToolboxAccessConfig) -> Self {
        let mut registry = HashMap::new();
        let mut order = Vec::new();

        for tool in tools {
            let name = canonical_tool_name(tool.name());
            if registry.contains_key(&name) {
                continue;
            }
            order.push(name.clone());
            registry.insert(
                name,
                ToolRegistration {
                    description: tool.description().to_string(),
                    categories: infer_tool_categories(tool.name()),
                    tool,
                },
            );
        }

        let available: HashSet<String> = order.iter().cloned().collect();
        let mut core = normalize_names(config.core_tools, &available);
        let mut discoverable = normalize_names(config.discoverable_tools, &available);

        if core.is_empty() && discoverable.is_empty() {
            core = available.clone();
        } else if discoverable.is_empty() {
            discoverable = available.difference(&core).cloned().collect();
        }

        let active = core.clone();

        Self {
            inner: Arc::new(Mutex::new(ToolboxState {
                registry,
                order,
                active,
                core,
                discoverable,
                iam_policy: config.iam_policy,
                iam_identity: config.iam_identity,
            })),
        }
    }

    pub fn register_system_tool(
        &self,
        tool: Arc<dyn Tool>,
        categories: impl IntoIterator<Item = &'static str>,
    ) {
        let mut guard = self.inner.lock();
        let name = canonical_tool_name(tool.name());
        let categories = categories
            .into_iter()
            .map(ToOwned::to_owned)
            .collect::<Vec<_>>();

        if !guard.registry.contains_key(&name) {
            guard.order.push(name.clone());
        }

        guard.registry.insert(
            name.clone(),
            ToolRegistration {
                description: tool.description().to_string(),
                categories,
                tool,
            },
        );
        guard.active.insert(name.clone());
        guard.core.insert(name);
    }

    pub fn active_tools_boxed(&self) -> Vec<Box<dyn Tool>> {
        let guard = self.inner.lock();
        ordered_entries(&guard, &guard.active)
            .into_iter()
            .map(|registration| {
                Box::new(ArcToolRef(Arc::clone(&registration.tool))) as Box<dyn Tool>
            })
            .collect()
    }

    pub fn active_tool_specs(&self) -> Vec<ToolSpec> {
        let guard = self.inner.lock();
        ordered_entries(&guard, &guard.active)
            .into_iter()
            .map(|registration| registration.tool.spec())
            .collect()
    }

    pub fn active_tool_names(&self) -> Vec<String> {
        let guard = self.inner.lock();
        guard
            .order
            .iter()
            .filter(|name| guard.active.contains(*name))
            .cloned()
            .collect()
    }

    pub fn active_tool(&self, name: &str) -> Option<Arc<dyn Tool>> {
        let guard = self.inner.lock();
        let canonical = canonical_tool_name(name);
        guard
            .active
            .contains(&canonical)
            .then(|| guard.registry.get(&canonical))
            .flatten()
            .map(|registration| Arc::clone(&registration.tool))
    }

    pub fn tool_entry(&self, name: &str) -> Option<ToolCatalogEntry> {
        let guard = self.inner.lock();
        let canonical = canonical_tool_name(name);
        entry_from_state(&guard, &canonical)
    }

    pub fn activate_tool(&self, name: &str) -> Result<ToolActivationResult> {
        let mut guard = self.inner.lock();
        let canonical = canonical_tool_name(name);

        if guard.active.contains(&canonical) {
            let tool = entry_from_state(&guard, &canonical)
                .ok_or_else(|| anyhow::anyhow!("tool '{canonical}' is no longer registered"))?;
            return Ok(ToolActivationResult {
                status: ToolActivationStatus::AlreadyActive,
                tool,
            });
        }

        if !guard.discoverable.contains(&canonical) {
            bail!("tool '{canonical}' is not discoverable for this agent");
        }

        if let Some(policy) = guard.iam_policy.as_ref() {
            let identity = guard.iam_identity.as_ref().ok_or_else(|| {
                anyhow::anyhow!("IAM identity is required to activate '{canonical}'")
            })?;
            match policy.evaluate_tool_access(identity, &canonical) {
                PolicyDecision::Allow => {}
                PolicyDecision::Deny(reason) => bail!(reason),
            }
        }

        guard.active.insert(canonical.clone());
        let tool = entry_from_state(&guard, &canonical)
            .ok_or_else(|| anyhow::anyhow!("tool '{canonical}' is no longer registered"))?;
        Ok(ToolActivationResult {
            status: ToolActivationStatus::Activated,
            tool,
        })
    }

    pub fn query(
        &self,
        category: Option<&str>,
        search: Option<&str>,
        max_results: usize,
    ) -> Vec<ToolCatalogEntry> {
        let guard = self.inner.lock();
        let normalized_category = category
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .map(|value| value.to_ascii_lowercase());
        let normalized_search = search
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .map(|value| value.to_ascii_lowercase());

        let mut entries = Vec::new();
        for name in &guard.order {
            if !guard.discoverable.contains(name) && !guard.active.contains(name) {
                continue;
            }

            let Some(entry) = entry_from_state(&guard, name) else {
                continue;
            };

            if let Some(ref category_filter) = normalized_category {
                if !entry
                    .categories
                    .iter()
                    .any(|category_name| category_name == category_filter)
                {
                    continue;
                }
            }

            if let Some(ref search_filter) = normalized_search {
                let haystack = format!(
                    "{} {} {}",
                    entry.name.to_ascii_lowercase(),
                    entry.description.to_ascii_lowercase(),
                    entry.categories.join(" ").to_ascii_lowercase()
                );
                if !haystack.contains(search_filter) {
                    continue;
                }
            }

            entries.push(entry);
            if entries.len() >= max_results {
                break;
            }
        }

        entries
    }

    pub fn category_counts(&self) -> BTreeMap<String, usize> {
        let guard = self.inner.lock();
        let mut counts = BTreeMap::new();
        for name in &guard.order {
            if !guard.discoverable.contains(name) {
                continue;
            }

            let Some(registration) = guard.registry.get(name) else {
                continue;
            };
            for category in &registration.categories {
                *counts.entry(category.clone()).or_insert(0) += 1;
            }
        }
        counts
    }

    pub fn discovery_prompt_section(&self) -> String {
        let guard = self.inner.lock();
        let mut grouped = BTreeMap::<String, Vec<String>>::new();

        for name in &guard.order {
            if !guard.discoverable.contains(name) || guard.active.contains(name) {
                continue;
            }
            let Some(registration) = guard.registry.get(name) else {
                continue;
            };
            let category = registration
                .categories
                .first()
                .cloned()
                .unwrap_or_else(|| "general".to_string());
            grouped.entry(category).or_default().push(name.clone());
        }

        if grouped.is_empty() {
            return String::new();
        }

        let mut output = String::from("## Discoverable Tools\n\n");
        output.push_str(
            "Only the active tools above are fully loaded. Additional tools can be loaded mid-session with `tool_discovery`.\n",
        );
        output.push_str(
            "Use `tool_discovery` with `action=\"query\"` to search by category or keyword, then `action=\"activate\"` to load the exact tool you need.\n\n",
        );
        for (category, names) in grouped {
            output.push_str("- ");
            output.push_str(&category);
            output.push_str(": ");
            output.push_str(&names.join(", "));
            output.push('\n');
        }
        output
    }

    pub fn fork_session(&self) -> Self {
        self.fork_session_with_exclusions(&[])
    }

    pub fn fork_session_with_exclusions(&self, excluded_tools: &[String]) -> Self {
        let guard = self.inner.lock();
        let excluded = excluded_tools
            .iter()
            .map(|name| canonical_tool_name(name))
            .collect::<HashSet<_>>();

        let active = guard
            .core
            .iter()
            .filter(|name| !excluded.contains(*name))
            .cloned()
            .collect::<HashSet<_>>();
        let core = active.clone();
        let discoverable = guard
            .discoverable
            .iter()
            .filter(|name| !excluded.contains(*name))
            .cloned()
            .collect::<HashSet<_>>();

        Self {
            inner: Arc::new(Mutex::new(ToolboxState {
                registry: guard.registry.clone(),
                order: guard.order.clone(),
                active,
                core,
                discoverable,
                iam_policy: guard.iam_policy.clone(),
                iam_identity: guard.iam_identity.clone(),
            })),
        }
    }
}

impl Default for ToolboxManager {
    fn default() -> Self {
        Self::from_registry(Vec::new(), ToolboxAccessConfig::default())
    }
}

fn canonical_tool_name(name: &str) -> String {
    let lowered = name.trim().to_ascii_lowercase();
    map_tool_name_alias(&lowered).to_ascii_lowercase()
}

fn normalize_names(names: Vec<String>, available: &HashSet<String>) -> HashSet<String> {
    names
        .into_iter()
        .map(|name| canonical_tool_name(&name))
        .filter(|name| available.contains(name))
        .collect()
}

fn ordered_entries<'a>(
    state: &'a ToolboxState,
    filter: &HashSet<String>,
) -> Vec<&'a ToolRegistration> {
    state
        .order
        .iter()
        .filter(|name| filter.contains(*name))
        .filter_map(|name| state.registry.get(name))
        .collect()
}

fn entry_from_state(state: &ToolboxState, name: &str) -> Option<ToolCatalogEntry> {
    let registration = state.registry.get(name)?;
    Some(ToolCatalogEntry {
        name: name.to_string(),
        description: registration.description.clone(),
        categories: registration.categories.clone(),
        active: state.active.contains(name),
        core: state.core.contains(name),
        discoverable: state.discoverable.contains(name),
    })
}

fn infer_tool_categories(name: &str) -> Vec<String> {
    let lowered = canonical_tool_name(name);
    let mut categories = BTreeSet::new();

    if lowered.starts_with("hardware_") {
        categories.insert("hardware".to_string());
    }

    if lowered.starts_with("browser")
        || lowered.starts_with("web_")
        || lowered.starts_with("http_")
        || matches!(
            lowered.as_str(),
            "text_browser" | "linkedin" | "notion" | "jira" | "google_workspace" | "microsoft365"
        )
    {
        categories.insert("web".to_string());
    }

    if lowered.starts_with("file_")
        || matches!(
            lowered.as_str(),
            "glob_search" | "content_search" | "pdf_read" | "git_operations"
        )
    {
        categories.insert("filesystem".to_string());
    }

    if lowered.starts_with("memory_") || lowered == "knowledge" {
        categories.insert("memory".to_string());
    }

    if lowered.starts_with("cron_") || lowered == "schedule" {
        categories.insert("automation".to_string());
    }

    if lowered == "delegate" || lowered == "swarm" {
        categories.insert("orchestration".to_string());
    }

    if lowered == "vi_verify" || lowered.starts_with("security_") {
        categories.insert("security".to_string());
    }

    if lowered == "calculator" || lowered.contains("physics") {
        categories.insert("physics".to_string());
    }

    if categories.is_empty() {
        categories.insert("general".to_string());
    }

    categories.into_iter().collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use async_trait::async_trait;
    use serde_json::json;

    struct DummyTool {
        name: &'static str,
        description: &'static str,
    }

    #[async_trait]
    impl Tool for DummyTool {
        fn name(&self) -> &str {
            self.name
        }

        fn description(&self) -> &str {
            self.description
        }

        fn parameters_schema(&self) -> serde_json::Value {
            json!({
                "type": "object",
                "properties": {}
            })
        }

        async fn execute(
            &self,
            _args: serde_json::Value,
        ) -> anyhow::Result<super::super::ToolResult> {
            Ok(super::super::ToolResult {
                success: true,
                output: self.name.to_string(),
                error: None,
            })
        }
    }

    fn registry(names: &[(&'static str, &'static str)]) -> Vec<Arc<dyn Tool>> {
        names
            .iter()
            .map(|(name, description)| Arc::new(DummyTool { name, description }) as Arc<dyn Tool>)
            .collect()
    }

    #[test]
    fn defaults_to_eager_activation_without_yellowstone_scope() {
        let toolbox = ToolboxManager::from_registry(
            registry(&[
                ("file_read", "Read files"),
                ("web_fetch", "Fetch a web page"),
            ]),
            ToolboxAccessConfig::default(),
        );

        assert_eq!(toolbox.active_tool_names(), vec!["file_read", "web_fetch"]);
        assert!(toolbox.discovery_prompt_section().is_empty());
    }

    #[test]
    fn activates_discoverable_tool_on_demand() {
        let toolbox = ToolboxManager::from_registry(
            registry(&[
                ("file_read", "Read files"),
                ("web_fetch", "Fetch a web page"),
            ]),
            ToolboxAccessConfig {
                core_tools: vec!["file_read".into()],
                discoverable_tools: vec!["web_fetch".into()],
                ..ToolboxAccessConfig::default()
            },
        );

        assert_eq!(toolbox.active_tool_names(), vec!["file_read"]);

        let activation = toolbox.activate_tool("web_fetch").unwrap();
        assert_eq!(activation.status, ToolActivationStatus::Activated);
        assert_eq!(toolbox.active_tool_names(), vec!["file_read", "web_fetch"]);
    }

    #[test]
    fn rejects_activation_outside_discoverable_scope() {
        let toolbox = ToolboxManager::from_registry(
            registry(&[
                ("file_read", "Read files"),
                ("web_fetch", "Fetch a web page"),
            ]),
            ToolboxAccessConfig {
                core_tools: vec!["file_read".into()],
                discoverable_tools: vec!["file_read".into()],
                ..ToolboxAccessConfig::default()
            },
        );

        let err = toolbox.activate_tool("web_fetch").unwrap_err().to_string();
        assert!(err.contains("not discoverable"));
    }

    #[test]
    fn respects_iam_policy_when_identity_is_available() {
        let policy = IamPolicy::from_mappings(&[crate::security::iam_policy::RoleMapping {
            nevis_role: "viewer".into(),
            rain_permissions: vec!["file_read".into()],
            workspace_access: vec!["all".into()],
        }])
        .unwrap();
        let identity = NevisIdentity {
            user_id: "user-1".into(),
            roles: vec!["viewer".into()],
            scopes: vec![],
            mfa_verified: true,
            session_expiry: u64::MAX,
        };
        let toolbox = ToolboxManager::from_registry(
            registry(&[
                ("file_read", "Read files"),
                ("web_fetch", "Fetch a web page"),
            ]),
            ToolboxAccessConfig {
                core_tools: vec!["file_read".into()],
                discoverable_tools: vec!["web_fetch".into()],
                iam_policy: Some(Arc::new(policy)),
                iam_identity: Some(identity),
            },
        );

        let err = toolbox.activate_tool("web_fetch").unwrap_err().to_string();
        assert!(err.contains("no role grants access"));
    }

    #[test]
    fn query_filters_by_category_and_keyword() {
        let toolbox = ToolboxManager::from_registry(
            registry(&[
                ("hardware_board_info", "Inspect board metadata"),
                ("web_fetch", "Fetch a web page"),
            ]),
            ToolboxAccessConfig {
                core_tools: vec![],
                discoverable_tools: vec!["hardware_board_info".into(), "web_fetch".into()],
                ..ToolboxAccessConfig::default()
            },
        );

        let hardware = toolbox.query(Some("hardware"), None, 10);
        assert_eq!(hardware.len(), 1);
        assert_eq!(hardware[0].name, "hardware_board_info");

        let keyword = toolbox.query(None, Some("page"), 10);
        assert_eq!(keyword.len(), 1);
        assert_eq!(keyword[0].name, "web_fetch");
    }
}
