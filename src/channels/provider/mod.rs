//! Provider management for channel message processing.
//!
//! This module handles provider lifecycle, caching, and route selection for
//! channel-based message processing. Each channel sender can have a different
//! provider configuration via model routing.
//!
//! ## Extracted from `channels/mod.rs`
//!
//! This module was extracted as part of the Phase 1 refactor to reduce
//! `channels/mod.rs` from 9,108 lines toward single-responsibility modules.

use crate::channels::ChannelRouteSelection;
use crate::channels::ModelCacheState;
use crate::providers::{self, Provider};
use anyhow::Context;
use parking_lot::Mutex;
use std::collections::HashMap;
use std::fmt::Write as _;
use std::path::Path;
use std::sync::Arc;

// ============================================================================
// Constants
// ============================================================================

/// Filename for cached model list (from provider API).
const MODEL_CACHE_FILE: &str = "models_cache.json";

/// Maximum number of models to show in cached preview.
const MODEL_CACHE_PREVIEW_LIMIT: usize = 10;

// ============================================================================
// Types
// ============================================================================

/// Shared provider cache map type.
pub type ProviderCacheMap = Arc<Mutex<HashMap<String, Arc<dyn Provider>>>>;

// ============================================================================
// Provider Manager
// ============================================================================

/// Manages provider lifecycle for channel message processing.
///
/// This struct wraps the channel runtime context's provider-related fields
/// and provides a clean API for getting or creating providers based on
/// route selection.
#[derive(Clone)]
pub struct ChannelProviderManager {
    /// The default provider (pre-built from global config).
    pub(crate) default_provider: Arc<dyn Provider>,
    /// The default provider name.
    pub(crate) default_provider_name: Arc<String>,
    /// Per-route API key overrides.
    pub(crate) global_api_key: Option<String>,
    /// Cached providers.
    pub(crate) cache: ProviderCacheMap,
    /// Reliability configuration.
    pub(crate) reliability: Arc<crate::config::ReliabilityConfig>,
    /// Provider runtime options.
    pub(crate) runtime_options: providers::ProviderRuntimeOptions,
    /// Default API URL (from global config).
    pub(crate) default_api_url: Option<String>,
}

impl ChannelProviderManager {
    /// Create a new provider manager from channel runtime context fields.
    ///
    /// # Arguments
    ///
    /// * `default_provider` — Pre-built default provider
    /// * `default_provider_name` — Name of the default provider
    /// * `global_api_key` — Global API key fallback
    /// * `cache` — Shared provider cache
    /// * `reliability` — Reliability configuration
    /// * `runtime_options` — Provider runtime options
    /// * `default_api_url` — Global API URL override
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        default_provider: Arc<dyn Provider>,
        default_provider_name: Arc<String>,
        global_api_key: Option<String>,
        cache: ProviderCacheMap,
        reliability: crate::config::ReliabilityConfig,
        runtime_options: providers::ProviderRuntimeOptions,
        default_api_url: Option<String>,
    ) -> Self {
        Self {
            default_provider,
            default_provider_name,
            global_api_key,
            cache,
            reliability: Arc::new(reliability),
            runtime_options,
            default_api_url,
        }
    }

    /// Get or create a provider for the given route.
    ///
    /// Uses caching to avoid re-creating providers. If a route-specific
    /// API key is provided, creates a separate cached entry to avoid
    /// cache poisoning.
    pub async fn get_or_create(
        &self,
        route: &ChannelRouteSelection,
    ) -> anyhow::Result<Arc<dyn Provider>> {
        self.get_or_create_with_key(&route.provider, route.api_key.as_deref())
            .await
    }

    /// Get or create a provider by name with optional credential override.
    ///
    /// If `api_key_override` is `None`, uses the global API key fallback.
    pub async fn get_or_create_with_key(
        &self,
        provider_name: &str,
        api_key_override: Option<&str>,
    ) -> anyhow::Result<Arc<dyn Provider>> {
        let cache_key = provider_cache_key(provider_name, api_key_override);

        // Check cache first
        if let Some(existing) = self.cache.lock().get(&cache_key).cloned() {
            return Ok(existing);
        }

        // Only return the default provider when there's no credential override
        if api_key_override.is_none() && provider_name == self.default_provider_name.as_str() {
            return Ok(Arc::clone(&self.default_provider));
        }

        // Determine API URL: use default URL only for the default provider
        let api_url = if provider_name == self.default_provider_name.as_str() {
            self.default_api_url.as_deref()
        } else {
            None
        };

        // Prefer route-specific credential; fall back to the global key
        let effective_api_key = api_key_override
            .map(ToString::to_string)
            .or_else(|| self.global_api_key.clone());

        let provider = create_resilient_provider_nonblocking(
            provider_name,
            effective_api_key,
            api_url.map(ToString::to_string),
            self.reliability.as_ref().clone(),
            self.runtime_options.clone(),
        )
        .await?;
        let provider: Arc<dyn Provider> = Arc::from(provider);

        // Warmup the provider
        if let Err(err) = provider.warmup().await {
            tracing::warn!(provider = provider_name, "Provider warmup failed: {err}");
        }

        // Cache the provider
        let mut cache = self.cache.lock();
        let cached = cache
            .entry(cache_key)
            .or_insert_with(|| Arc::clone(&provider));
        Ok(Arc::clone(cached))
    }

    /// Get the default provider without caching lookup.
    pub fn default_provider(&self) -> Arc<dyn Provider> {
        Arc::clone(&self.default_provider)
    }
}

/// Build a cache key that includes the provider name and, when a
/// route-specific API key is supplied, a hash of that key. This prevents
/// cache poisoning when multiple routes target the same provider with
/// different credentials.
pub fn provider_cache_key(provider_name: &str, route_api_key: Option<&str>) -> String {
    match route_api_key {
        Some(key) => {
            use std::hash::{Hash, Hasher};
            let mut hasher = std::collections::hash_map::DefaultHasher::new();
            key.hash(&mut hasher);
            format!("{provider_name}@{:x}", hasher.finish())
        }
        None => provider_name.to_string(),
    }
}

/// Load cached model preview from workspace for a provider.
pub fn load_cached_model_preview(workspace_dir: &Path, provider_name: &str) -> Vec<String> {
    let cache_path = workspace_dir.join("state").join(MODEL_CACHE_FILE);
    let Ok(raw) = std::fs::read_to_string(cache_path) else {
        return Vec::new();
    };
    let Ok(state) = serde_json::from_str::<ModelCacheState>(&raw) else {
        return Vec::new();
    };

    state
        .entries
        .into_iter()
        .find(|entry| entry.provider == provider_name)
        .map(|entry| {
            entry
                .models
                .into_iter()
                .take(MODEL_CACHE_PREVIEW_LIMIT)
                .collect::<Vec<_>>()
        })
        .unwrap_or_default()
}

/// Build help response showing current model and available cached models.
pub fn build_models_help_response(
    current: &ChannelRouteSelection,
    workspace_dir: &Path,
    model_routes: &[crate::config::ModelRouteConfig],
) -> String {
    let mut response = String::new();
    let _ = writeln!(
        response,
        "Current provider: `{}`\nCurrent model: `{}`",
        current.provider, current.model
    );
    response.push_str("\nSwitch model with `/model <model-id>` or `/model <hint>`.\n");

    if !model_routes.is_empty() {
        response.push_str("\nConfigured model routes:\n");
        for route in model_routes {
            let _ = writeln!(
                response,
                "  `{}` → {} ({})",
                route.hint, route.model, route.provider
            );
        }
    }

    let cached_models = load_cached_model_preview(workspace_dir, &current.provider);
    if cached_models.is_empty() {
        let _ = writeln!(
            response,
            "\nNo cached model list found for `{}`. Ask the operator to run `R.A.I.N. models refresh --provider {}`.",
            current.provider, current.provider
        );
    } else {
        let _ = writeln!(
            response,
            "\nCached model IDs (top {}):",
            cached_models.len()
        );
        for model in cached_models {
            let _ = writeln!(response, "- `{model}`");
        }
    }

    response
}

/// Build help response showing current provider and available providers.
pub fn build_providers_help_response(current: &ChannelRouteSelection) -> String {
    let mut response = String::new();
    let _ = writeln!(
        response,
        "Current provider: `{}`\nCurrent model: `{}`",
        current.provider, current.model
    );
    response.push_str("\nSwitch provider with `/models <provider>`.\n");
    response.push_str("Switch model with `/model <model-id>`.\n\n");
    response.push_str("Available providers:\n");
    for provider in providers::list_providers() {
        if provider.aliases.is_empty() {
            let _ = writeln!(response, "- {}", provider.name);
        } else {
            let _ = writeln!(
                response,
                "- {} (aliases: {})",
                provider.name,
                provider.aliases.join(", ")
            );
        }
    }
    response
}

// ============================================================================
// Internal helpers
// ============================================================================

/// Create a resilient provider in a blocking task to avoid blocking async runtime.
async fn create_resilient_provider_nonblocking(
    provider_name: &str,
    api_key: Option<String>,
    api_url: Option<String>,
    reliability: crate::config::ReliabilityConfig,
    provider_runtime_options: providers::ProviderRuntimeOptions,
) -> anyhow::Result<Box<dyn Provider>> {
    let provider_name = provider_name.to_string();
    let result: anyhow::Result<Box<dyn Provider>> = tokio::task::spawn_blocking(move || {
        providers::create_resilient_provider_with_options(
            &provider_name,
            api_key.as_deref(),
            api_url.as_deref(),
            &reliability,
            &provider_runtime_options,
        )
    })
    .await
    .context("failed to join provider initialization task")?;
    result
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_provider_cache_key_without_key() {
        let key = provider_cache_key("openai", None);
        assert_eq!(key, "openai");
    }

    #[test]
    fn test_provider_cache_key_with_different_keys_produces_different_keys() {
        let key1 = provider_cache_key("openai", Some("sk-key1"));
        let key2 = provider_cache_key("openai", Some("sk-key2"));
        // Same provider, different keys should produce different cache keys
        assert_ne!(key1, key2);
    }

    #[test]
    fn test_load_cached_model_preview_nonexistent_dir() {
        let dir = std::path::Path::new("/nonexistent/path");
        let models = load_cached_model_preview(dir, "openai");
        assert!(models.is_empty());
    }
}
