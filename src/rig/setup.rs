//! `rain rig setup`: discover what exists, explain what is missing, and
//! write `[rig]` configuration only after explicit confirmation.
//!
//! Setup never downloads models, installs binaries, changes services or
//! firewall rules, or opens network listeners. It only edits `config.toml`.

use super::capability::CapabilityState;
use super::context::{RigContext, selected_provider};
use super::status::{RigStatus, collect};
use crate::config::{
    Config, RigConfig, RigPrivacyMode, RigProfileKind, builtin_rig_profile, validate_rig_node_name,
};
use anyhow::{Context, Result, bail};
use std::fmt::Write as _;
use std::io::{IsTerminal, Write};
use std::path::Path;

/// Operator choices from CLI flags.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct SetupRequest {
    pub profile: Option<RigProfileKind>,
    pub node_name: Option<String>,
    pub privacy: Option<RigPrivacyMode>,
    pub yes: bool,
    pub dry_run: bool,
}

/// Concrete config changes.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SetupPlan {
    pub rig: RigConfig,
    /// `(provider, model)` to select when switching to a running local server.
    pub switch_provider: Option<(String, Option<String>)>,
    /// Clear `api_url` because it belonged to the previous provider.
    pub clear_api_url: bool,
    /// Human explanations (missing components, consequences).
    pub notes: Vec<String>,
}

fn install_hint(id: &str) -> Option<&'static str> {
    match id {
        "llamacpp" => Some(
            "llama.cpp: install llama-server (https://github.com/ggml-org/llama.cpp), then run `llama-server -m <model.gguf> --port 8080`",
        ),
        "ollama" => Some(
            "Ollama: install from https://ollama.com, then `ollama serve` and `ollama pull <model>`",
        ),
        "lmstudio" => {
            Some("LM Studio: install from https://lmstudio.ai and start its local server")
        }
        "reticulum" => Some("Reticulum: optional, `pip install rns`, then start `rnsd`"),
        "lxmf" => Some("LXMF: optional, `pip install lxmf`, then configure `lxmd`"),
        _ => None,
    }
}

/// Build the plan from discovered state (pure; unit-tested).
pub fn plan(config: &Config, status: &RigStatus, request: &SetupRequest) -> Result<SetupPlan> {
    let profile_kind = request
        .profile
        .or(config.rig.profile)
        .unwrap_or(RigProfileKind::Local);
    let profile = builtin_rig_profile(profile_kind)?;
    let node_name = request
        .node_name
        .clone()
        .or_else(|| config.rig.node_name.clone());
    if let Some(name) = node_name.as_deref() {
        validate_rig_node_name(name)?;
    }
    let rig = RigConfig {
        profile: Some(profile_kind),
        node_name,
        privacy: request.privacy.or(config.rig.privacy),
    };
    let privacy = rig.effective_privacy().0;

    let mut notes = Vec::new();
    let mut switch_provider = None;
    let current = selected_provider(config);
    let current_display = crate::providers::locality::display_provider_id(&current);
    let current_is_local =
        crate::providers::locality::resolve_inference_target(&current, config.api_url.as_deref())
            .locality
            .is_local();

    let running_preferred = profile.preferred_inference.iter().find_map(|id| {
        status
            .get(id)
            .filter(|cap| cap.state == CapabilityState::Running)
            .map(|cap| (id.clone(), cap))
    });

    if privacy == RigPrivacyMode::Local && !current_is_local {
        match running_preferred {
            Some((id, cap)) => {
                let model = cap
                    .inference
                    .as_ref()
                    .and_then(|detail| detail.models.first().cloned());
                notes.push(format!(
                    "default provider '{current_display}' is hosted; local privacy would refuse it, so setup selects the running {} server",
                    cap.name
                ));
                switch_provider = Some((id, model));
            }
            None => notes.push(format!(
                "default provider '{current_display}' is hosted and no local server is running: with local privacy the runtime will refuse inference until you start one and re-run `rain rig setup` (or choose --privacy hybrid)"
            )),
        }
    }

    for id in &profile.preferred_inference {
        let running = status
            .get(id)
            .is_some_and(|cap| cap.state == CapabilityState::Running);
        if !running {
            if let Some(hint) = install_hint(id) {
                notes.push(format!("not running · {hint}"));
            }
        }
    }
    for id in &profile.wanted_capabilities {
        let present = status.get(id).is_some_and(|cap| {
            matches!(
                cap.state,
                CapabilityState::Running | CapabilityState::Available | CapabilityState::Configured
            )
        });
        if !present {
            let hint = install_hint(id).unwrap_or("see docs/rig/getting-started.md");
            notes.push(format!("profile expects '{id}' · {hint}"));
        }
    }
    let clear_api_url = switch_provider.is_some() && config.api_url.is_some();
    Ok(SetupPlan {
        rig,
        switch_provider,
        clear_api_url,
        notes,
    })
}

/// Apply a plan to the on-disk config file.
///
/// Edits the TOML document directly instead of re-serializing the runtime
/// `Config`, so environment overrides (API keys, providers) are never
/// persisted and every other key, including encrypted secrets, is kept as
/// written. The result is parsed and validated before an atomic replace.
pub fn write_plan(config_path: &Path, plan: &SetupPlan) -> Result<()> {
    let raw = std::fs::read_to_string(config_path)
        .with_context(|| format!("reading {}", config_path.display()))?;
    let mut document: toml::Table =
        toml::from_str(&raw).with_context(|| format!("parsing {}", config_path.display()))?;
    document.insert("rig".into(), toml::Value::try_from(&plan.rig)?);
    if let Some((provider, model)) = &plan.switch_provider {
        // Drop serde aliases so the canonical keys are the only ones present.
        document.remove("model_provider");
        document.insert("default_provider".into(), provider.clone().into());
        if let Some(model) = model {
            document.remove("model");
            document.insert("default_model".into(), model.clone().into());
        }
    }
    if plan.clear_api_url {
        document.remove("api_url");
    }
    let rendered = toml::to_string(&document)?;
    let parsed: Config = toml::from_str(&rendered).context("updated config does not parse")?;
    parsed.rig.validate()?;

    let temp = config_path.with_extension("toml.rig-setup.tmp");
    std::fs::write(&temp, rendered).with_context(|| format!("writing {}", temp.display()))?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mode = std::fs::metadata(config_path).map_or(0o600, |meta| meta.permissions().mode());
        std::fs::set_permissions(&temp, std::fs::Permissions::from_mode(mode))?;
    }
    std::fs::rename(&temp, config_path)
        .with_context(|| format!("replacing {}", config_path.display()))?;
    Ok(())
}

fn render_plan(config: &Config, plan: &SetupPlan) -> String {
    let mut out = String::new();
    let _ = writeln!(out, "R.A.I.N. RIG SETUP\n");
    let _ = writeln!(out, "Changes to {}:", config.config_path.display());
    let _ = writeln!(out, "  [rig]");
    if let Some(profile) = plan.rig.profile {
        let _ = writeln!(out, "  profile   = \"{profile}\"");
    }
    let _ = writeln!(out, "  node_name = \"{}\"", plan.rig.node_name());
    let (privacy, _) = plan.rig.effective_privacy();
    match plan.rig.privacy {
        Some(explicit) => {
            let _ = writeln!(out, "  privacy   = \"{explicit}\"");
        }
        None => {
            let _ = writeln!(
                out,
                "  (privacy defaults to \"{privacy}\" from the profile)"
            );
        }
    }
    if let Some((provider, model)) = &plan.switch_provider {
        let _ = writeln!(out, "  default_provider = \"{provider}\"");
        if let Some(model) = model {
            let _ = writeln!(out, "  default_model    = \"{model}\"");
        }
    }
    if plan.clear_api_url {
        let _ = writeln!(
            out,
            "  api_url          = (removed; it belonged to the previous provider)"
        );
    }
    if !plan.notes.is_empty() {
        let _ = writeln!(out, "\nNotes:");
        for note in &plan.notes {
            let _ = writeln!(out, "  - {note}");
        }
    }
    let _ = writeln!(
        out,
        "\nSetup does not download models, install software, change services or firewall rules, or open listeners."
    );
    out
}

fn confirm(prompt: &str) -> Result<bool> {
    print!("{prompt} [y/N]: ");
    std::io::stdout().flush()?;
    let mut answer = String::new();
    std::io::stdin().read_line(&mut answer)?;
    Ok(matches!(
        answer.trim().to_ascii_lowercase().as_str(),
        "y" | "yes"
    ))
}

/// Run setup end to end.
pub async fn run(config: &Config, ctx: &RigContext, request: SetupRequest) -> Result<()> {
    let status = collect(ctx).await;
    let plan = plan(config, &status, &request)?;
    print!("{}", render_plan(config, &plan));
    if request.dry_run {
        println!("\nDry run: nothing written.");
        return Ok(());
    }
    if !request.yes {
        if !std::io::stdin().is_terminal() {
            bail!(
                "refusing to write config without confirmation in non-interactive mode; pass --yes"
            );
        }
        if !confirm("\nWrite these changes?")? {
            println!("Setup cancelled; nothing written.");
            return Ok(());
        }
    }
    write_plan(&config.config_path, &plan)?;
    println!("Saved. Next: `rain rig doctor`, then `rain rig status`.");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::rig::capability::{CapabilityStatus, InferenceDetail};
    use crate::rig::test_support::context;

    fn status_with(capabilities: Vec<CapabilityStatus>) -> RigStatus {
        let ctx = context();
        let privacy = crate::rig::system::assess_privacy(&ctx);
        let network = crate::rig::system::network_status(&ctx, &privacy);
        RigStatus {
            schema_version: 1,
            identity: crate::rig::identity::build_identity("rain-local", &capabilities),
            runtime: crate::rig::status::RuntimeInfo {
                version: "test".into(),
                profile: None,
                profile_summary: None,
                library_found: false,
                default_provider: "openrouter".into(),
                default_model: None,
            },
            privacy,
            network,
            capabilities,
            readiness: crate::rig::status::NodeReadiness::Ready,
            reasons: vec![],
            notices: vec![],
        }
    }

    fn running_llamacpp() -> CapabilityStatus {
        CapabilityStatus::new("llamacpp", CapabilityState::Running, "ready").with_inference(
            InferenceDetail {
                provider: "llamacpp".into(),
                locality: "local".into(),
                models: vec!["Qwen3-4B-Q4_K_M.gguf".into()],
                ..InferenceDetail::default()
            },
        )
    }

    #[test]
    fn local_profile_switches_hosted_default_to_running_llamacpp() {
        let mut config = Config::default();
        config.default_provider = Some("openrouter".into());
        config.api_url = Some("https://openrouter.ai/api/v1".into());
        let plan = plan(
            &config,
            &status_with(vec![running_llamacpp()]),
            &SetupRequest::default(),
        )
        .unwrap();
        assert_eq!(plan.rig.profile, Some(RigProfileKind::Local));
        assert_eq!(
            plan.switch_provider,
            Some(("llamacpp".into(), Some("Qwen3-4B-Q4_K_M.gguf".into())))
        );
        assert!(plan.clear_api_url);

        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("config.toml");
        std::fs::write(
            &path,
            "default_provider = \"openrouter\"\napi_url = \"https://openrouter.ai/api/v1\"\napi_key = \"enc2:kept-as-is\"\n",
        )
        .unwrap();
        write_plan(&path, &plan).unwrap();
        let written = std::fs::read_to_string(&path).unwrap();
        assert!(
            written.contains("enc2:kept-as-is"),
            "secrets are untouched: {written}"
        );
        let updated: Config = toml::from_str(&written).unwrap();
        assert_eq!(updated.default_provider.as_deref(), Some("llamacpp"));
        assert_eq!(
            updated.default_model.as_deref(),
            Some("Qwen3-4B-Q4_K_M.gguf")
        );
        assert!(updated.api_url.is_none());
        assert!(
            crate::providers::provider_runtime_options_from_config(&updated).local_inference_only
        );
    }

    #[test]
    fn no_running_server_keeps_provider_and_explains() {
        let config = Config::default();
        let plan = plan(&config, &status_with(vec![]), &SetupRequest::default()).unwrap();
        assert!(plan.switch_provider.is_none());
        assert!(
            plan.notes
                .iter()
                .any(|n| n.contains("will refuse inference"))
        );
        assert!(plan.notes.iter().any(|n| n.contains("llama-server")));
    }

    #[test]
    fn hybrid_privacy_leaves_hosted_provider_alone() {
        let config = Config::default();
        let request = SetupRequest {
            profile: Some(RigProfileKind::Node),
            privacy: Some(RigPrivacyMode::Hybrid),
            node_name: Some("lab-node".into()),
            ..SetupRequest::default()
        };
        let plan = plan(&config, &status_with(vec![running_llamacpp()]), &request).unwrap();
        assert!(plan.switch_provider.is_none());
        assert_eq!(plan.rig.node_name(), "lab-node");
        assert_eq!(plan.rig.privacy, Some(RigPrivacyMode::Hybrid));
    }

    #[test]
    fn invalid_node_name_is_rejected_before_writing() {
        let request = SetupRequest {
            node_name: Some("My Laptop".into()),
            ..SetupRequest::default()
        };
        assert!(plan(&Config::default(), &status_with(vec![]), &request).is_err());
    }

    #[tokio::test]
    async fn dry_run_writes_nothing() {
        let dir = tempfile::tempdir().unwrap();
        let mut config = Config::default();
        config.config_path = dir.path().join("config.toml");
        config.workspace_dir = dir.path().join("workspace");
        let mut ctx = context();
        ctx.config = config.clone();
        Box::pin(run(
            &config,
            &ctx,
            SetupRequest {
                dry_run: true,
                ..SetupRequest::default()
            },
        ))
        .await
        .unwrap();
        assert!(!config.config_path.exists());
    }

    #[tokio::test]
    async fn confirmed_setup_writes_rig_section() {
        let dir = tempfile::tempdir().unwrap();
        let mut config = Config::default();
        config.config_path = dir.path().join("config.toml");
        config.workspace_dir = dir.path().join("workspace");
        // Runtime-only value (as if from an env override) must not be persisted.
        std::fs::write(&config.config_path, "default_temperature = 0.7\n").unwrap();
        config.api_key = Some("from-environment".into());
        let mut ctx = context();
        ctx.config = config.clone();
        Box::pin(run(
            &config,
            &ctx,
            SetupRequest {
                profile: Some(RigProfileKind::Field),
                privacy: Some(RigPrivacyMode::Hybrid),
                yes: true,
                ..SetupRequest::default()
            },
        ))
        .await
        .unwrap();
        let written = std::fs::read_to_string(&config.config_path).unwrap();
        assert!(written.contains("[rig]"), "{written}");
        assert!(written.contains("profile = \"field\""));
        assert!(written.contains("default_temperature = 0.7"));
        assert!(
            !written.contains("from-environment"),
            "env overrides leaked: {written}"
        );
    }

    #[test]
    fn write_plan_replaces_aliases_and_rejects_missing_file() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("config.toml");
        let plan = SetupPlan {
            rig: RigConfig {
                profile: Some(RigProfileKind::Local),
                ..RigConfig::default()
            },
            switch_provider: Some(("llamacpp".into(), Some("m.gguf".into()))),
            clear_api_url: false,
            notes: vec![],
        };
        assert!(
            write_plan(&path, &plan).is_err(),
            "missing config must not be created"
        );
        std::fs::write(&path, "model_provider = \"openrouter\"\nmodel = \"x\"\n").unwrap();
        write_plan(&path, &plan).unwrap();
        let updated: Config = toml::from_str(&std::fs::read_to_string(&path).unwrap()).unwrap();
        assert_eq!(updated.default_provider.as_deref(), Some("llamacpp"));
        assert_eq!(updated.default_model.as_deref(), Some("m.gguf"));
    }
}
