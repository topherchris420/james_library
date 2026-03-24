//! Plugin host: discovery, loading, lifecycle management.

use super::error::PluginError;
use super::{
    AgentPackInfo, PluginCapability, PluginInfo, PluginManifest, PluginPermission,
    AGENT_MANIFEST_SCHEMA_VERSION,
};
use reqwest::Url;
use std::collections::HashMap;
use std::path::{Path, PathBuf};

/// Manages the lifecycle of WASM plugins.
pub struct PluginHost {
    plugins_dir: PathBuf,
    loaded: HashMap<String, LoadedPlugin>,
    agent_registry: HashMap<PathBuf, AgentPackInfo>,
}

struct LoadedPlugin {
    manifest: PluginManifest,
    manifest_dir: PathBuf,
    wasm_path: PathBuf,
}

impl PluginHost {
    /// Create a new plugin host with the given plugins directory.
    pub fn new(workspace_dir: &Path) -> Result<Self, PluginError> {
        let plugins_dir = workspace_dir.join("plugins");
        if !plugins_dir.exists() {
            std::fs::create_dir_all(&plugins_dir)?;
        }

        let mut host = Self {
            plugins_dir,
            loaded: HashMap::new(),
            agent_registry: HashMap::new(),
        };

        host.discover()?;
        Ok(host)
    }

    /// Discover plugins in the plugins directory.
    fn discover(&mut self) -> Result<(), PluginError> {
        if !self.plugins_dir.exists() {
            return Ok(());
        }

        let entries = std::fs::read_dir(&self.plugins_dir)?;
        for entry in entries.flatten() {
            let path = entry.path();
            // Skip hidden/internal directories (e.g. .marketplace-staging)
            if path
                .file_name()
                .map_or(false, |n| n.to_string_lossy().starts_with('.'))
            {
                continue;
            }
            if path.is_dir() {
                let manifest_path = path.join("manifest.toml");
                if manifest_path.exists() {
                    if let Ok(manifest) = self.load_manifest(&manifest_path) {
                        let wasm_path = path.join(&manifest.wasm_path);
                        let manifest_dir = manifest_path.parent().unwrap_or(&path).to_path_buf();
                        self.loaded.insert(
                            manifest.name.clone(),
                            LoadedPlugin {
                                manifest,
                                manifest_dir,
                                wasm_path,
                            },
                        );
                    }
                }
            }
        }

        self.rebuild_agent_registry()?;
        Ok(())
    }

    fn load_manifest(&self, path: &Path) -> Result<PluginManifest, PluginError> {
        let content = std::fs::read_to_string(path)?;
        let manifest: PluginManifest = toml::from_str(&content)?;
        Ok(manifest)
    }

    /// List all discovered plugins.
    pub fn list_plugins(&self) -> Vec<PluginInfo> {
        self.loaded
            .values()
            .map(|p| PluginInfo {
                name: p.manifest.name.clone(),
                version: p.manifest.version.clone(),
                description: p.manifest.description.clone(),
                tags: p.manifest.tags.clone(),
                min_runtime_version: p.manifest.min_runtime_version.clone(),
                signature: p.manifest.signature.clone(),
                capabilities: p.manifest.capabilities.clone(),
                permissions: p.manifest.permissions.clone(),
                wasm_path: p.wasm_path.clone(),
                loaded: p.wasm_path.exists(),
            })
            .collect()
    }

    /// Get info about a specific plugin.
    pub fn get_plugin(&self, name: &str) -> Option<PluginInfo> {
        self.loaded.get(name).map(|p| PluginInfo {
            name: p.manifest.name.clone(),
            version: p.manifest.version.clone(),
            description: p.manifest.description.clone(),
            tags: p.manifest.tags.clone(),
            min_runtime_version: p.manifest.min_runtime_version.clone(),
            signature: p.manifest.signature.clone(),
            capabilities: p.manifest.capabilities.clone(),
            permissions: p.manifest.permissions.clone(),
            wasm_path: p.wasm_path.clone(),
            loaded: p.wasm_path.exists(),
        })
    }

    /// Install a plugin from a directory path.
    pub fn install(&mut self, source: &str) -> Result<(), PluginError> {
        self.install_with_policy(source, false, &all_permissions())
    }

    /// Install a plugin with config-driven trust controls.
    pub fn install_with_policy(
        &mut self,
        source: &str,
        marketplace_enabled: bool,
        allowed_permissions: &[String],
    ) -> Result<(), PluginError> {
        let marketplace_url = parse_marketplace_source(source);
        if marketplace_url.is_some() && !marketplace_enabled {
            return Err(PluginError::PermissionDenied {
                plugin: source.to_string(),
                permission: "plugins.marketplace_enabled".to_string(),
            });
        }

        let source_path = PathBuf::from(source);
        let manifest_path = if let Some(url) = marketplace_url.as_ref() {
            self.fetch_marketplace_manifest(url)?
        } else if source_path.is_dir() {
            source_path.join("manifest.toml")
        } else {
            source_path.clone()
        };

        if !manifest_path.exists() {
            return Err(PluginError::NotFound(format!(
                "manifest.toml not found at {}",
                manifest_path.display()
            )));
        }

        let manifest = self.load_manifest(&manifest_path)?;

        // Validate manifest fields against path traversal before any file operations.
        validate_relative_path(&manifest.name, "plugin name")?;
        validate_relative_path(&manifest.wasm_path, "wasm_path")?;
        for agent_manifest in &manifest.agent_manifests {
            validate_relative_path(agent_manifest, "agent_manifests entry")?;
        }

        self.validate_requested_permissions(&manifest, allowed_permissions)?;
        let source_dir = manifest_path
            .parent()
            .ok_or_else(|| PluginError::InvalidManifest("no parent directory".into()))?;

        let wasm_source = if let Some(url) = marketplace_url.as_ref() {
            self.fetch_marketplace_file(url, source_dir, &manifest.wasm_path)?
        } else {
            source_dir.join(&manifest.wasm_path)
        };
        if !wasm_source.exists() {
            return Err(PluginError::NotFound(format!(
                "WASM file not found: {}",
                wasm_source.display()
            )));
        }

        if let Some(url) = marketplace_url.as_ref() {
            for agent_manifest in &manifest.agent_manifests {
                let _ = self.fetch_marketplace_file(url, source_dir, agent_manifest)?;
            }
        }

        if self.loaded.contains_key(&manifest.name) {
            return Err(PluginError::AlreadyLoaded(manifest.name));
        }

        // Copy plugin to plugins directory
        let dest_dir = self.plugins_dir.join(&manifest.name);
        std::fs::create_dir_all(&dest_dir)?;

        // Copy manifest
        std::fs::copy(&manifest_path, dest_dir.join("manifest.toml"))?;

        // Copy WASM file
        let wasm_dest = dest_dir.join(&manifest.wasm_path);
        if let Some(parent) = wasm_dest.parent() {
            std::fs::create_dir_all(parent)?;
        }
        std::fs::copy(&wasm_source, &wasm_dest)?;

        // Copy declared agent manifests
        for agent_manifest in &manifest.agent_manifests {
            let src = source_dir.join(agent_manifest);
            if !src.exists() {
                return Err(PluginError::NotFound(format!(
                    "Agent manifest not found: {}",
                    src.display()
                )));
            }
            let dest = dest_dir.join(agent_manifest);
            if let Some(parent) = dest.parent() {
                std::fs::create_dir_all(parent)?;
            }
            std::fs::copy(src, dest)?;
        }

        self.loaded.insert(
            manifest.name.clone(),
            LoadedPlugin {
                manifest,
                manifest_dir: dest_dir,
                wasm_path: wasm_dest,
            },
        );

        // Clean up marketplace staging directory if it exists.
        let staging_dir = self.plugins_dir.join(".marketplace-staging");
        if staging_dir.exists() {
            let _ = std::fs::remove_dir_all(&staging_dir);
        }

        self.rebuild_agent_registry()?;
        Ok(())
    }

    /// Remove a plugin by name.
    pub fn remove(&mut self, name: &str) -> Result<(), PluginError> {
        if self.loaded.remove(name).is_none() {
            return Err(PluginError::NotFound(name.to_string()));
        }

        let plugin_dir = self.plugins_dir.join(name);
        if plugin_dir.exists() {
            std::fs::remove_dir_all(plugin_dir)?;
        }

        self.rebuild_agent_registry()?;
        Ok(())
    }

    /// Get tool-capable plugins.
    pub fn tool_plugins(&self) -> Vec<&PluginManifest> {
        self.loaded
            .values()
            .filter(|p| p.manifest.capabilities.contains(&PluginCapability::Tool))
            .map(|p| &p.manifest)
            .collect()
    }

    /// Get channel-capable plugins.
    pub fn channel_plugins(&self) -> Vec<&PluginManifest> {
        self.loaded
            .values()
            .filter(|p| p.manifest.capabilities.contains(&PluginCapability::Channel))
            .map(|p| &p.manifest)
            .collect()
    }

    /// List plugin-provided agent packs registered from local manifests.
    pub fn list_agent_packs(&self) -> Vec<AgentPackInfo> {
        self.agent_registry.values().cloned().collect()
    }

    /// Get the in-memory registry of resolved plugin-provided agent manifests.
    pub fn agent_registry(&self) -> &HashMap<PathBuf, AgentPackInfo> {
        &self.agent_registry
    }

    /// Returns the plugins directory path.
    pub fn plugins_dir(&self) -> &Path {
        &self.plugins_dir
    }

    fn rebuild_agent_registry(&mut self) -> Result<(), PluginError> {
        self.agent_registry.clear();

        for loaded in self.loaded.values() {
            for relative_manifest in &loaded.manifest.agent_manifests {
                let resolved = loaded.manifest_dir.join(relative_manifest);
                let info = self.register_agent_manifest(
                    &loaded.manifest.name,
                    &resolved,
                    &loaded.manifest.tags,
                    loaded.manifest.min_runtime_version.as_deref(),
                    loaded.manifest.signature.as_deref(),
                )?;
                self.agent_registry.insert(resolved, info);
            }
        }

        Ok(())
    }

    fn register_agent_manifest(
        &self,
        plugin_name: &str,
        manifest_path: &Path,
        plugin_tags: &[String],
        min_runtime_version: Option<&str>,
        signature: Option<&str>,
    ) -> Result<AgentPackInfo, PluginError> {
        if !manifest_path.exists() {
            return Err(PluginError::NotFound(format!(
                "agent manifest not found: {}",
                manifest_path.display()
            )));
        }

        let content = std::fs::read_to_string(manifest_path)?;
        let value: toml::Value = toml::from_str(&content)?;
        let schema_version = extract_schema_version(&value).ok_or_else(|| {
            PluginError::InvalidManifest(format!(
                "agent manifest '{}' must define integer schema_version",
                manifest_path.display()
            ))
        })?;
        if schema_version > AGENT_MANIFEST_SCHEMA_VERSION {
            return Err(PluginError::InvalidManifest(format!(
                "agent manifest '{}' schema_version {} is newer than supported {}",
                manifest_path.display(),
                schema_version,
                AGENT_MANIFEST_SCHEMA_VERSION
            )));
        }

        Ok(AgentPackInfo {
            plugin: plugin_name.to_string(),
            manifest_path: manifest_path.to_path_buf(),
            schema_version,
            tags: plugin_tags.to_vec(),
            min_runtime_version: min_runtime_version.map(str::to_string),
            signature: signature.map(str::to_string),
        })
    }

    fn validate_requested_permissions(
        &self,
        manifest: &PluginManifest,
        allowed_permissions: &[String],
    ) -> Result<(), PluginError> {
        for permission in &manifest.permissions {
            let key = permission_key(permission);
            if !allowed_permissions.iter().any(|p| p == key) {
                return Err(PluginError::PermissionDenied {
                    plugin: manifest.name.clone(),
                    permission: key.to_string(),
                });
            }
        }
        Ok(())
    }

    fn fetch_marketplace_manifest(&self, source: &Url) -> Result<PathBuf, PluginError> {
        let manifest_url = if source.path().ends_with("manifest.toml") {
            source.clone()
        } else {
            let mut base = source.clone();
            if !base.path().ends_with('/') {
                base.set_path(&format!("{}/", base.path()));
            }
            base
                .join("manifest.toml")
                .map_err(|e| PluginError::LoadFailed(format!("invalid marketplace URL: {e}")))?
        };

        let content = reqwest::blocking::get(manifest_url.clone())
            .map_err(|e| PluginError::LoadFailed(format!("failed to fetch {manifest_url}: {e}")))?
            .error_for_status()
            .map_err(|e| PluginError::LoadFailed(format!("failed to fetch {manifest_url}: {e}")))?
            .text()
            .map_err(|e| {
                PluginError::LoadFailed(format!("failed to read response from {manifest_url}: {e}"))
            })?;

        let staging_dir = self.plugins_dir.join(".marketplace-staging");
        std::fs::create_dir_all(&staging_dir)?;
        let manifest_path = staging_dir.join("manifest.toml");
        std::fs::write(&manifest_path, content)?;
        Ok(manifest_path)
    }

    fn fetch_marketplace_file(
        &self,
    fn fetch_marketplace_file(
        &self,
        source: &Url,
        staging_dir: &Path,
        relative_path: &str,
    ) -> Result<PathBuf, PluginError> {
        let mut base = source.clone();
        if !base.path().ends_with('/') {
            base.set_path(&format!("{}/", base.path()));
        }
        let remote = base.join(relative_path).map_err(|e| {
            PluginError::LoadFailed(format!("invalid marketplace artifact URL: {e}"))
        })?;
        let bytes = reqwest::blocking::get(remote.clone())
            .map_err(|e| PluginError::LoadFailed(format!("failed to fetch {remote}: {e}")))?
            .error_for_status()
            .map_err(|e| PluginError::LoadFailed(format!("failed to fetch {remote}: {e}")))?
            .bytes()
            .map_err(|e| PluginError::LoadFailed(format!("failed to read {remote}: {e}")))?;

        let local = staging_dir.join(relative_path);
        if let Some(parent) = local.parent() {
            std::fs::create_dir_all(parent)?;
        }
        std::fs::write(&local, bytes)?;
        Ok(local)
    }
}

/// Ensure a URL ends with a trailing slash so that `Url::join` appends
/// rather than replacing the last path segment (RFC 3986 behaviour).
fn ensure_trailing_slash(url: &Url) -> Url {
    let mut base = url.clone();
    if !base.path().ends_with('/') {
        base.set_path(&format!("{}/", base.path()));
    }
    base
}

/// Reject paths that could escape the target directory.
fn validate_relative_path(path: &str, field_name: &str) -> Result<(), PluginError> {
    if path.is_empty() {
        return Err(PluginError::InvalidManifest(format!(
            "{field_name} must not be empty"
        )));
    }
    let p = std::path::Path::new(path);
    if p.is_absolute() {
        return Err(PluginError::InvalidManifest(format!(
            "{field_name} contains absolute path: {path}"
        )));
    }
    for component in p.components() {
        if matches!(component, std::path::Component::ParentDir) {
            return Err(PluginError::InvalidManifest(format!(
                "{field_name} contains path traversal (..): {path}"
            )));
        }
    }
    Ok(())
}

fn parse_marketplace_source(source: &str) -> Option<Url> {
    Url::parse(source)
        .ok()
        .filter(|url| matches!(url.scheme(), "http" | "https"))
}

fn extract_schema_version(value: &toml::Value) -> Option<u32> {
    value
        .get("schema_version")
        .and_then(toml::Value::as_integer)
        .and_then(|v| u32::try_from(v).ok())
}

fn permission_key(permission: &PluginPermission) -> &'static str {
    match permission {
        PluginPermission::HttpClient => "http_client",
        PluginPermission::FileRead => "file_read",
        PluginPermission::FileWrite => "file_write",
        PluginPermission::EnvRead => "env_read",
        PluginPermission::MemoryRead => "memory_read",
        PluginPermission::MemoryWrite => "memory_write",
    }
}

fn all_permissions() -> Vec<String> {
    vec![
        "http_client".to_string(),
        "file_read".to_string(),
        "file_write".to_string(),
        "env_read".to_string(),
        "memory_read".to_string(),
        "memory_write".to_string(),
    ]
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn test_empty_plugin_dir() {
        let dir = tempdir().unwrap();
        let host = PluginHost::new(dir.path()).unwrap();
        assert!(host.list_plugins().is_empty());
    }

    #[test]
    fn test_discover_with_manifest() {
        let dir = tempdir().unwrap();
        let plugin_dir = dir.path().join("plugins").join("test-plugin");
        std::fs::create_dir_all(&plugin_dir).unwrap();

        std::fs::write(
            plugin_dir.join("manifest.toml"),
            r#"
name = "test-plugin"
version = "0.1.0"
description = "A test plugin"
wasm_path = "plugin.wasm"
capabilities = ["tool"]
permissions = []
"#,
        )
        .unwrap();

        let host = PluginHost::new(dir.path()).unwrap();
        let plugins = host.list_plugins();
        assert_eq!(plugins.len(), 1);
        assert_eq!(plugins[0].name, "test-plugin");
    }

    #[test]
    fn test_tool_plugins_filter() {
        let dir = tempdir().unwrap();
        let plugins_base = dir.path().join("plugins");

        // Tool plugin
        let tool_dir = plugins_base.join("my-tool");
        std::fs::create_dir_all(&tool_dir).unwrap();
        std::fs::write(
            tool_dir.join("manifest.toml"),
            r#"
name = "my-tool"
version = "0.1.0"
wasm_path = "tool.wasm"
capabilities = ["tool"]
"#,
        )
        .unwrap();

        // Channel plugin
        let chan_dir = plugins_base.join("my-channel");
        std::fs::create_dir_all(&chan_dir).unwrap();
        std::fs::write(
            chan_dir.join("manifest.toml"),
            r#"
name = "my-channel"
version = "0.1.0"
wasm_path = "channel.wasm"
capabilities = ["channel"]
"#,
        )
        .unwrap();

        let host = PluginHost::new(dir.path()).unwrap();
        assert_eq!(host.list_plugins().len(), 2);
        assert_eq!(host.tool_plugins().len(), 1);
        assert_eq!(host.channel_plugins().len(), 1);
        assert_eq!(host.tool_plugins()[0].name, "my-tool");
    }

    #[test]
    fn test_get_plugin() {
        let dir = tempdir().unwrap();
        let plugin_dir = dir.path().join("plugins").join("lookup-test");
        std::fs::create_dir_all(&plugin_dir).unwrap();
        std::fs::write(
            plugin_dir.join("manifest.toml"),
            r#"
name = "lookup-test"
version = "1.0.0"
description = "Lookup test"
wasm_path = "plugin.wasm"
capabilities = ["tool"]
"#,
        )
        .unwrap();

        let host = PluginHost::new(dir.path()).unwrap();
        assert!(host.get_plugin("lookup-test").is_some());
        assert!(host.get_plugin("nonexistent").is_none());
    }

    #[test]
    fn test_remove_plugin() {
        let dir = tempdir().unwrap();
        let plugin_dir = dir.path().join("plugins").join("removable");
        std::fs::create_dir_all(&plugin_dir).unwrap();
        std::fs::write(
            plugin_dir.join("manifest.toml"),
            r#"
name = "removable"
version = "0.1.0"
wasm_path = "plugin.wasm"
capabilities = ["tool"]
"#,
        )
        .unwrap();

        let mut host = PluginHost::new(dir.path()).unwrap();
        assert_eq!(host.list_plugins().len(), 1);

        host.remove("removable").unwrap();
        assert!(host.list_plugins().is_empty());
        assert!(!plugin_dir.exists());
    }

    #[test]
    fn test_remove_nonexistent_returns_error() {
        let dir = tempdir().unwrap();
        let mut host = PluginHost::new(dir.path()).unwrap();
        assert!(host.remove("ghost").is_err());
    }

    #[test]
    fn test_discover_agent_pack_manifests() {
        let dir = tempdir().unwrap();
        let plugin_dir = dir.path().join("plugins").join("agent-plugin");
        std::fs::create_dir_all(plugin_dir.join("agents")).unwrap();

        std::fs::write(
            plugin_dir.join("manifest.toml"),
            r#"
name = "agent-plugin"
version = "0.3.0"
wasm_path = "plugin.wasm"
agent_manifests = ["agents/researcher.toml"]
tags = ["research", "pack"]
min_runtime_version = "0.20.0"
signature = "sig:abc123"
capabilities = ["tool"]
"#,
        )
        .unwrap();
        std::fs::write(
            plugin_dir.join("agents").join("researcher.toml"),
            r#"
schema_version = 1
name = "researcher"
"#,
        )
        .unwrap();

        let host = PluginHost::new(dir.path()).unwrap();
        let packs = host.list_agent_packs();
        assert_eq!(packs.len(), 1);
        assert_eq!(packs[0].plugin, "agent-plugin");
        assert_eq!(packs[0].schema_version, 1);
        assert_eq!(packs[0].tags, vec!["research", "pack"]);
    }

    #[test]
    fn test_discover_agent_pack_schema_version_incompatible_fails_fast() {
        let dir = tempdir().unwrap();
        let plugin_dir = dir.path().join("plugins").join("bad-agent-pack");
        std::fs::create_dir_all(plugin_dir.join("agents")).unwrap();

        std::fs::write(
            plugin_dir.join("manifest.toml"),
            r#"
name = "bad-agent-pack"
version = "0.1.0"
wasm_path = "plugin.wasm"
agent_manifests = ["agents/latest.toml"]
capabilities = ["tool"]
"#,
        )
        .unwrap();
        std::fs::write(
            plugin_dir.join("agents").join("latest.toml"),
            r#"
schema_version = 999
name = "future-pack"
"#,
        )
        .unwrap();

        let result = PluginHost::new(dir.path());
        assert!(matches!(result, Err(PluginError::InvalidManifest(_))));
    }

    #[test]
    fn test_install_with_policy_rejects_disallowed_permissions() {
        let dir = tempdir().unwrap();
        let source = dir.path().join("source-plugin");
        std::fs::create_dir_all(&source).unwrap();
        std::fs::write(source.join("plugin.wasm"), b"\0asm").unwrap();
        std::fs::write(
            source.join("manifest.toml"),
            r#"
name = "perm-test"
version = "1.0.0"
wasm_path = "plugin.wasm"
capabilities = ["tool"]
permissions = ["env_read"]
"#,
        )
        .unwrap();

        let mut host = PluginHost::new(dir.path()).unwrap();
        let allowed_permissions = vec!["http_client".to_string()];

        let err = host
            .install_with_policy(source.to_str().unwrap(), false, &allowed_permissions)
            .unwrap_err();
        assert!(matches!(
            err,
            PluginError::PermissionDenied { permission, .. } if permission == "env_read"
        ));
    }
}
