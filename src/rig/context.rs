//! Inputs to Rig discovery: config, an environment snapshot, the research
//! library location, and the local endpoints to probe.
//!
//! Everything a probe reads comes through [`RigContext`], so tests can
//! substitute mock servers and environment values deterministically.

use super::probe::ProbeClient;
use crate::config::Config;
use crate::providers::locality::{
    LLAMACPP_DEFAULT_BASE_URL, LMSTUDIO_DEFAULT_BASE_URL, OLLAMA_DEFAULT_BASE_URL,
};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

/// Environment variables consulted by the Rig. Secret-bearing variables are
/// only checked for presence; their values are never reported.
pub const RIG_ENV_KEYS: &[&str] = &[
    "RAIN_DECISION_MODE",
    "RAIN_LAYA_CHECKPOINT",
    "RAIN_JUDGMENT_PROVIDER",
    "TYPESAFE_API_KEY",
    "RAIN_LLM_BASE_URL",
    "LM_STUDIO_BASE_URL",
    "RAIN_LLM_MODEL",
    "LM_STUDIO_MODEL",
    "rain_PROVIDER_URL",
];

/// Snapshot of [`RIG_ENV_KEYS`].
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct RigEnv {
    vars: BTreeMap<String, String>,
}

impl RigEnv {
    pub fn from_process() -> Self {
        Self::from_pairs(
            RIG_ENV_KEYS
                .iter()
                .filter_map(|key| std::env::var(key).ok().map(|value| (*key, value))),
        )
    }

    pub fn from_pairs<'a>(pairs: impl IntoIterator<Item = (&'a str, impl Into<String>)>) -> Self {
        Self {
            vars: pairs
                .into_iter()
                .map(|(key, value)| (key.to_string(), value.into()))
                .collect(),
        }
    }

    /// Trimmed, non-empty value.
    pub fn get(&self, key: &str) -> Option<&str> {
        self.vars
            .get(key)
            .map(|value| value.trim())
            .filter(|value| !value.is_empty())
    }

    pub fn is_set(&self, key: &str) -> bool {
        self.get(key).is_some()
    }
}

/// Base URLs of the local inference servers the Rig probes.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProbeEndpoints {
    pub llamacpp: String,
    pub ollama: String,
    pub lmstudio: String,
}

impl ProbeEndpoints {
    /// Endpoints the runtime would use: the configured `api_url` applies to
    /// the configured default provider, everything else uses its default.
    pub fn from_config(config: &Config, env: &RigEnv) -> Self {
        let selected = selected_provider(config);
        let api_url = config
            .api_url
            .as_deref()
            .map(str::trim)
            .filter(|url| !url.is_empty());
        let for_provider = |aliases: &[&str], default: &str| -> String {
            match api_url {
                Some(url) if aliases.contains(&selected.as_str()) => url.to_string(),
                _ => default.to_string(),
            }
        };
        let ollama = env
            .get("rain_PROVIDER_URL")
            .filter(|_| selected == "ollama")
            .map_or_else(
                || for_provider(&["ollama"], OLLAMA_DEFAULT_BASE_URL),
                str::to_string,
            );
        Self {
            llamacpp: for_provider(&["llamacpp", "llama.cpp"], LLAMACPP_DEFAULT_BASE_URL),
            ollama,
            // The factory ignores api_url for LM Studio.
            lmstudio: LMSTUDIO_DEFAULT_BASE_URL.to_string(),
        }
    }
}

/// Normalized configured default provider id (`openrouter` when unset).
pub fn selected_provider(config: &Config) -> String {
    config
        .default_provider
        .as_deref()
        .map(str::trim)
        .filter(|name| !name.is_empty())
        .unwrap_or("openrouter")
        .to_string()
}

/// Everything a Rig discovery pass needs.
#[derive(Debug, Clone)]
pub struct RigContext {
    pub config: Config,
    pub env: RigEnv,
    pub library_root: Option<PathBuf>,
    pub endpoints: ProbeEndpoints,
    pub probe: ProbeClient,
}

impl RigContext {
    /// Context for the running process.
    pub fn from_runtime(config: &Config, library: Option<&Path>) -> Self {
        let env = RigEnv::from_process();
        let endpoints = ProbeEndpoints::from_config(config, &env);
        Self {
            config: config.clone(),
            env,
            library_root: resolve_library_root(library),
            endpoints,
            probe: ProbeClient::new(),
        }
    }

    /// Directory for Rig state (disposition log). Inside the workspace.
    pub fn state_dir(&self) -> PathBuf {
        self.config.workspace_dir.join("rig")
    }
}

/// A directory is the research library when it holds the launcher and at
/// least one persona file.
pub fn is_library_root(dir: &Path) -> bool {
    dir.join("rain_lab.py").is_file() && dir.join("JAMES_SOUL.md").is_file()
}

/// Locate the research library: explicit path, then the current directory
/// and its ancestors, then ancestors of the running binary (a source build
/// lives in `<checkout>/target/<profile>/rain`).
pub fn resolve_library_root(explicit: Option<&Path>) -> Option<PathBuf> {
    if let Some(path) = explicit {
        return is_library_root(path).then(|| path.to_path_buf());
    }
    let from_cwd = std::env::current_dir().ok();
    let from_exe = std::env::current_exe().ok();
    [from_cwd, from_exe]
        .into_iter()
        .flatten()
        .flat_map(|start| {
            start
                .ancestors()
                .take(5)
                .map(Path::to_path_buf)
                .collect::<Vec<_>>()
        })
        .find(|candidate| is_library_root(candidate))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn env_snapshot_trims_and_ignores_empty() {
        let env =
            RigEnv::from_pairs([("RAIN_DECISION_MODE", " laya "), ("TYPESAFE_API_KEY", "  ")]);
        assert_eq!(env.get("RAIN_DECISION_MODE"), Some("laya"));
        assert!(!env.is_set("TYPESAFE_API_KEY"));
        assert!(!env.is_set("RAIN_LLM_MODEL"));
    }

    #[test]
    fn probe_endpoints_use_existing_defaults() {
        let endpoints = ProbeEndpoints::from_config(&Config::default(), &RigEnv::default());
        assert_eq!(endpoints.llamacpp, "http://localhost:8080/v1");
        assert_eq!(endpoints.ollama, "http://localhost:11434");
        assert_eq!(endpoints.lmstudio, "http://localhost:1234/v1");
    }

    #[test]
    fn probe_endpoints_apply_api_url_only_to_selected_provider() {
        let mut config = Config::default();
        config.default_provider = Some("llama.cpp".into());
        config.api_url = Some("http://127.0.0.1:8033/v1".into());
        let endpoints = ProbeEndpoints::from_config(&config, &RigEnv::default());
        assert_eq!(endpoints.llamacpp, "http://127.0.0.1:8033/v1");
        assert_eq!(endpoints.ollama, "http://localhost:11434");

        config.default_provider = Some("ollama".into());
        let env = RigEnv::from_pairs([("rain_PROVIDER_URL", "http://10.0.0.2:11434")]);
        let endpoints = ProbeEndpoints::from_config(&config, &env);
        assert_eq!(endpoints.ollama, "http://10.0.0.2:11434");
        assert_eq!(endpoints.llamacpp, "http://localhost:8080/v1");
    }

    #[test]
    fn library_root_requires_launcher_and_persona() {
        let dir = tempfile::tempdir().unwrap();
        assert!(!is_library_root(dir.path()));
        assert_eq!(resolve_library_root(Some(dir.path())), None);
        std::fs::write(dir.path().join("rain_lab.py"), "").unwrap();
        std::fs::write(dir.path().join("JAMES_SOUL.md"), "# James").unwrap();
        assert_eq!(
            resolve_library_root(Some(dir.path())),
            Some(dir.path().to_path_buf())
        );
    }
}
