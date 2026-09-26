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
    let mut rig = RigConfig {
        profile: Some(profile_kind),
        node_name,
        privacy: request.privacy.or(config.rig.privacy),
        meeting: config.rig.meeting.clone(),
        bridge: config.rig.bridge.clone(),
        radio: config.rig.radio.clone(),
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
        match running_preferred.clone() {
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

    // Pin the Python meeting to a running local server when it would be hosted.
    let meeting_hosted = status
        .get("lab-meeting")
        .and_then(|cap| cap.inference.as_ref())
        .is_some_and(|detail| detail.locality == "remote");
    if meeting_hosted {
        let pin = running_preferred.and_then(|(id, cap)| {
            let detail = cap.inference.as_ref()?;
            let endpoint = detail.endpoint.clone()?;
            let base_url = if id == "ollama" {
                format!("{}/v1", endpoint.trim_end_matches('/'))
            } else {
                endpoint
            };
            Some((cap.name.clone(), base_url, detail.models.first().cloned()?))
        });
        match (pin, privacy) {
            (Some((server, base_url, model)), RigPrivacyMode::Local) => {
                notes.push(format!(
                    "the meeting would use a hosted model; setup pins [rig.meeting] to the running {server} server"
                ));
                rig.meeting = Some(crate::config::RigMeetingConfig {
                    base_url: Some(base_url),
                    model: Some(model),
                });
            }
            (Some((server, _, _)), _) => notes.push(format!(
                "the meeting uses a hosted model; rerun with --privacy local to pin it to the running {server} server"
            )),
            (None, RigPrivacyMode::Local) => notes.push(
                "the meeting uses a hosted model and no local server is running: under local privacy the meeting refuses to start until one runs (then re-run `rain rig setup`)".to_string(),
            ),
            (None, _) => {}
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

/// Keys `write_plan` may change; everything else must survive verbatim.
const MANAGED_TOP_LEVEL_KEYS: &[&str] = &[
    "rig",
    "default_provider",
    "model_provider",
    "default_model",
    "model",
    "api_url",
];

/// Table header name of a line (`[a.b]` / `[[a.b]]`), if it is one.
fn header_name(line: &str) -> Option<String> {
    let trimmed = line.trim();
    let inner = trimmed
        .strip_prefix("[[")
        .and_then(|rest| rest.split_once("]]"))
        .or_else(|| {
            trimmed
                .strip_prefix('[')
                .and_then(|rest| rest.split_once(']'))
        })?;
    let (name, trailing) = inner;
    let trailing = trailing.trim();
    (trailing.is_empty() || trailing.starts_with('#')).then(|| name.trim().to_string())
}

/// Top-level key assigned on a line (`key = …`, `key.sub = …`).
fn assigned_key(line: &str) -> Option<&str> {
    let trimmed = line.trim_start();
    if trimmed.starts_with('#') {
        return None;
    }
    let (key, _) = trimmed.split_once('=')?;
    let key = key.trim().trim_matches('"');
    let first = key.split('.').next()?.trim().trim_matches('"');
    (!first.is_empty()).then_some(first)
}

fn is_rig_table(name: &str) -> bool {
    name == "rig" || name.starts_with("rig.")
}

/// Rewrite config text in place: replace the `[rig]` tables and the managed
/// top-level keys, keeping every other line (including comments) verbatim.
pub fn edit_config_text(raw: &str, plan: &SetupPlan) -> Result<String> {
    let newline = if raw.contains("\r\n") { "\r\n" } else { "\n" };
    let lines: Vec<&str> = raw.lines().collect();
    let first_header = lines
        .iter()
        .position(|line| header_name(line).is_some())
        .unwrap_or(lines.len());

    let mut replacements: Vec<(&str, Option<String>)> = Vec::new();
    if let Some((provider, model)) = &plan.switch_provider {
        replacements.push(("default_provider", Some(provider.clone())));
        replacements.push(("model_provider", None));
        if let Some(model) = model {
            replacements.push(("default_model", Some(model.clone())));
            replacements.push(("model", None));
        }
    }
    if plan.clear_api_url {
        replacements.push(("api_url", None));
    }
    let render =
        |key: &str, value: &str| format!("{key} = {}", toml::Value::String(value.to_string()));

    let mut out: Vec<String> = Vec::with_capacity(lines.len() + 8);
    let mut placed: Vec<&str> = Vec::new();
    let mut index = 0;
    while index < lines.len() {
        let line = lines[index];
        if index < first_header {
            match assigned_key(line) {
                // Inline `rig = {…}` / dotted `rig.x = …`: replaced by the table below.
                Some("rig") => {}
                Some(key) => match replacements.iter().find(|(k, _)| *k == key) {
                    Some((k, Some(value))) => {
                        out.push(render(k, value));
                        placed.push(k);
                    }
                    Some((_, None)) => {}
                    None => out.push(line.to_string()),
                },
                None => out.push(line.to_string()),
            }
            index += 1;
            if index == first_header {
                // Insert managed keys the file did not have, before the first table.
                let insert_at = out
                    .iter()
                    .rposition(|l| !l.trim().is_empty())
                    .map_or(0, |i| i + 1);
                let missing: Vec<String> = replacements
                    .iter()
                    .filter(|(k, v)| v.is_some() && !placed.contains(k))
                    .map(|(k, v)| render(k, v.as_deref().unwrap_or_default()))
                    .collect();
                out.splice(insert_at..insert_at, missing);
                placed.extend(replacements.iter().map(|(k, _)| *k));
            }
            continue;
        }
        if header_name(line).is_some_and(|name| is_rig_table(&name)) {
            // Skip the rig table body, but keep trailing comments/blank lines
            // that belong to the next table.
            let next = lines[index + 1..]
                .iter()
                .position(|l| header_name(l).is_some())
                .map_or(lines.len(), |offset| index + 1 + offset);
            let mut keep_from = next;
            while keep_from > index + 1 {
                let previous = lines[keep_from - 1].trim();
                if previous.is_empty() || previous.starts_with('#') {
                    keep_from -= 1;
                } else {
                    break;
                }
            }
            out.extend(lines[keep_from..next].iter().map(|l| (*l).to_string()));
            index = next;
            continue;
        }
        out.push(line.to_string());
        index += 1;
    }
    if first_header == lines.len() {
        // No tables at all: managed keys not yet placed go at the end.
        for (key, value) in &replacements {
            if let Some(value) = value {
                if !placed.contains(key) {
                    out.push(render(key, value));
                }
            }
        }
    }

    #[derive(serde::Serialize)]
    struct RigOnly<'a> {
        rig: &'a RigConfig,
    }
    let rig_block = toml::to_string(&RigOnly { rig: &plan.rig })?;
    while out.last().is_some_and(|l| l.trim().is_empty()) {
        out.pop();
    }
    if !out.is_empty() {
        out.push(String::new());
    }
    out.extend(rig_block.trim_end().lines().map(str::to_string));
    let mut rendered = out.join(newline);
    rendered.push_str(newline);
    Ok(rendered)
}

/// Apply a plan to the on-disk config file.
///
/// Edits the file text instead of re-serializing the runtime `Config`, so
/// comments and formatting survive, environment overrides (API keys,
/// providers) are never persisted, and encrypted secrets stay as written.
/// Before an atomic replace, the result must parse, its `[rig]` must
/// validate, and every unmanaged top-level value must be unchanged.
pub fn write_plan(config_path: &Path, plan: &SetupPlan) -> Result<()> {
    let raw = std::fs::read_to_string(config_path)
        .with_context(|| format!("reading {}", config_path.display()))?;
    let before: toml::Table =
        toml::from_str(&raw).with_context(|| format!("parsing {}", config_path.display()))?;
    let rendered = edit_config_text(&raw, plan)?;
    let after: toml::Table = toml::from_str(&rendered).context("updated config does not parse")?;
    for (key, value) in &before {
        if !MANAGED_TOP_LEVEL_KEYS.contains(&key.as_str()) && after.get(key) != Some(value) {
            bail!("refusing to write: editing would change unrelated key '{key}'");
        }
    }
    let parsed: Config = toml::from_str(&rendered).context("updated config does not parse")?;
    if parsed.rig != plan.rig {
        bail!("refusing to write: [rig] did not round-trip");
    }
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
    if let Some(meeting) = &plan.rig.meeting {
        let _ = writeln!(out, "  [rig.meeting]");
        if let Some(url) = &meeting.base_url {
            let _ = writeln!(out, "  base_url = \"{url}\"");
        }
        if let Some(model) = &meeting.model {
            let _ = writeln!(out, "  model    = \"{model}\"");
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
                endpoint: Some("http://localhost:8080/v1".into()),
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

    fn hosted_meeting() -> CapabilityStatus {
        CapabilityStatus::new("lab-meeting", CapabilityState::Unavailable, "x").with_inference(
            InferenceDetail {
                provider: "rain-lab-meeting".into(),
                locality: "remote".into(),
                ..InferenceDetail::default()
            },
        )
    }

    #[test]
    fn local_setup_pins_hosted_meeting_to_running_server() {
        let config = Config::default();
        let local_plan = plan(
            &config,
            &status_with(vec![running_llamacpp(), hosted_meeting()]),
            &SetupRequest::default(),
        )
        .unwrap();
        let meeting = local_plan.rig.meeting.clone().unwrap();
        assert_eq!(
            meeting.base_url.as_deref(),
            Some("http://localhost:8080/v1")
        );
        assert_eq!(meeting.model.as_deref(), Some("Qwen3-4B-Q4_K_M.gguf"));

        let hybrid = SetupRequest {
            privacy: Some(RigPrivacyMode::Hybrid),
            ..SetupRequest::default()
        };
        let hybrid_plan = plan(
            &config,
            &status_with(vec![running_llamacpp(), hosted_meeting()]),
            &hybrid,
        )
        .unwrap();
        assert!(hybrid_plan.rig.meeting.is_none());
        assert!(
            hybrid_plan
                .notes
                .iter()
                .any(|n| n.contains("--privacy local"))
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
    fn write_plan_preserves_comments_and_unrelated_tables() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("config.toml");
        let original = "# my R.A.I.N. config\n\
default_provider = \"openrouter\" # hosted for now\n\
api_url = \"https://openrouter.ai/api/v1\"\n\
default_temperature = 0.7\n\
\n\
# old rig settings\n\
[rig]\n\
profile = \"node\"\n\
\n\
[rig.meeting]\n\
model = \"old\"\n\
\n\
# Gateway: keep on loopback!\n\
[gateway]\n\
host = \"127.0.0.1\" # never 0.0.0.0\n\
port = 42617\n";
        std::fs::write(&path, original).unwrap();
        let plan = SetupPlan {
            rig: RigConfig {
                profile: Some(RigProfileKind::Local),
                meeting: Some(crate::config::RigMeetingConfig {
                    base_url: Some("http://localhost:8080/v1".into()),
                    model: Some("m.gguf".into()),
                }),
                ..RigConfig::default()
            },
            switch_provider: Some(("llamacpp".into(), Some("m.gguf".into()))),
            clear_api_url: true,
            notes: vec![],
        };
        write_plan(&path, &plan).unwrap();
        let written = std::fs::read_to_string(&path).unwrap();
        for kept in [
            "# my R.A.I.N. config",
            "# Gateway: keep on loopback!",
            "host = \"127.0.0.1\" # never 0.0.0.0",
            "default_temperature = 0.7",
        ] {
            assert!(written.contains(kept), "lost {kept:?}:\n{written}");
        }
        assert!(!written.contains("api_url"));
        assert!(!written.contains("model = \"old\""));
        assert!(written.contains("default_provider = \"llamacpp\""));
        assert!(written.contains("default_model = \"m.gguf\""));
        let updated: Config = toml::from_str(&written).unwrap();
        assert_eq!(updated.rig, plan.rig);
        assert_eq!(updated.gateway.port, 42617);
    }

    #[test]
    fn edit_handles_inline_rig_and_configs_without_tables() {
        let plan = SetupPlan {
            rig: RigConfig {
                profile: Some(RigProfileKind::Field),
                ..RigConfig::default()
            },
            switch_provider: None,
            clear_api_url: false,
            notes: vec![],
        };
        let edited = edit_config_text("rig = { profile = \"node\" }\n# note\n", &plan).unwrap();
        let parsed: Config = toml::from_str(&edited).unwrap();
        assert_eq!(parsed.rig.profile, Some(RigProfileKind::Field));
        assert!(edited.contains("# note"));
        let crlf = edit_config_text("a_comment = 1\r\n", &plan);
        assert!(crlf.unwrap().contains("\r\n[rig]\r\n"));
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
