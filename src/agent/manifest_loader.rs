use crate::agent::manifest::AgentManifest;
use crate::agent::tool_call_parser::map_tool_name_alias;
use anyhow::{Context, Result, bail};
use std::collections::HashSet;
use std::path::Path;

pub fn load_manifest(path: &Path) -> Result<AgentManifest> {
    let raw = std::fs::read_to_string(path)
        .with_context(|| format!("failed to read manifest: {}", path.display()))?;

    let mut manifest: AgentManifest = if path
        .extension()
        .and_then(std::ffi::OsStr::to_str)
        .is_some_and(|ext| ext.eq_ignore_ascii_case("json"))
    {
        serde_json::from_str(&raw).context("failed to parse JSON agent manifest")?
    } else {
        toml::from_str(&raw).context("failed to parse TOML agent manifest")?
    };

    validate_manifest(&manifest)?;
    normalize_tool_names(&mut manifest.tools.allow);
    normalize_tool_names(&mut manifest.tools.deny);
    normalize_tool_names(&mut manifest.tools.core_tools);
    normalize_tool_names(&mut manifest.tools.discoverable_tools);
    validate_tool_scopes(&manifest)?;

    Ok(manifest)
}

fn validate_manifest(manifest: &AgentManifest) -> Result<()> {
    if manifest.schema_version.trim().is_empty() {
        bail!("manifest.schema_version is required");
    }
    if manifest.tools.allow.is_empty() {
        bail!("manifest.tools.allow must contain at least one tool");
    }
    if manifest
        .tools
        .allow
        .iter()
        .any(|tool| tool.trim().is_empty())
    {
        bail!("manifest.tools.allow cannot contain empty tool names");
    }
    if let Some(memory) = &manifest.memory {
        if let Some(limit) = memory.recall_limit {
            if limit == 0 {
                bail!("manifest.memory.recall_limit must be >= 1");
            }
        }
        if let Some(score) = memory.min_relevance_score {
            if !(0.0..=1.0).contains(&score) {
                bail!("manifest.memory.min_relevance_score must be within 0.0..=1.0");
            }
        }
    }
    Ok(())
}

fn validate_tool_scopes(manifest: &AgentManifest) -> Result<()> {
    let allow_set: HashSet<&str> = manifest.tools.allow.iter().map(String::as_str).collect();

    for name in &manifest.tools.core_tools {
        if !allow_set.contains(name.as_str()) {
            bail!("manifest.tools.core_tools must be a subset of manifest.tools.allow");
        }
    }

    for name in &manifest.tools.discoverable_tools {
        if !allow_set.contains(name.as_str()) {
            bail!("manifest.tools.discoverable_tools must be a subset of manifest.tools.allow");
        }
    }

    Ok(())
}

fn normalize_tool_names(names: &mut Vec<String>) {
    let mut seen = HashSet::new();
    let mut normalized = Vec::with_capacity(names.len());

    for name in names.iter() {
        let trimmed = name.trim();
        if trimmed.is_empty() {
            continue;
        }
        let lowered = trimmed.to_ascii_lowercase();
        let canonical = map_tool_name_alias(&lowered).to_ascii_lowercase();
        if seen.insert(canonical.clone()) {
            normalized.push(canonical);
        }
    }

    *names = normalized;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn load_manifest_normalizes_tool_aliases() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("agent_manifest.toml");
        std::fs::write(
            &path,
            r#"
                schema_version = "1"

                [identity]
                name = "R.A.I.N.Agent"
                system_prompt = "Act safely"

                [tools]
                allow = ["BASH", "fileList", "shell"]
                deny = ["Http"]
                core_tools = [" shell "]
                discoverable_tools = [" fileList "]
                session_scope = "current"
            "#,
        )
        .unwrap();

        let manifest = load_manifest(&path).unwrap();
        assert_eq!(manifest.tools.allow, vec!["shell", "file_list"]);
        assert_eq!(manifest.tools.deny, vec!["http_request"]);
        assert_eq!(manifest.tools.core_tools, vec!["shell"]);
        assert_eq!(manifest.tools.discoverable_tools, vec!["file_list"]);
    }

    #[test]
    fn load_manifest_rejects_missing_allowlist() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("agent_manifest.toml");
        std::fs::write(
            &path,
            r#"
                schema_version = "1"

                [identity]
                name = "R.A.I.N.Agent"

                [tools]
                allow = []
                session_scope = "current"
            "#,
        )
        .unwrap();

        let err = load_manifest(&path).unwrap_err().to_string();
        assert!(err.contains("manifest.tools.allow"));
    }

    #[test]
    fn load_manifest_rejects_core_tools_outside_allowlist() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("agent_manifest.toml");
        std::fs::write(
            &path,
            r#"
                schema_version = "1"

                [identity]
                name = "R.A.I.N.Agent"

                [tools]
                allow = ["shell"]
                core_tools = ["file_read"]
                session_scope = "current"
            "#,
        )
        .unwrap();

        let err = load_manifest(&path).unwrap_err().to_string();
        assert!(err.contains("core_tools"));
    }

    #[test]
    fn load_manifest_rejects_out_of_range_relevance() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("agent_manifest.toml");
        std::fs::write(
            &path,
            r#"
                schema_version = "1"

                [identity]
                name = "R.A.I.N.Agent"

                [tools]
                allow = ["shell"]
                session_scope = "current"

                [memory]
                min_relevance_score = 1.2
            "#,
        )
        .unwrap();

        let err = load_manifest(&path).unwrap_err().to_string();
        assert!(err.contains("min_relevance_score"));
    }
}
