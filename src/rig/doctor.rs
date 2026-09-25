//! `rain rig doctor`: actionable checks with PASS / WARN / FAIL / SKIP.
//!
//! Missing optional extensions are `SKIP`, never `FAIL`, unless the selected
//! profile expects them (then `WARN`). `FAIL` is reserved for problems that
//! stop the configured node from working or that contradict policy.

use super::capability::{CapabilityCategory, CapabilityState, CapabilityStatus};
use super::context::RigContext;
use super::research::MeetingInference;
use super::status::{RigStatus, collect};
use super::system::BindExposure;
use crate::config::{RigPrivacyMode, builtin_rig_profile};
use crate::providers::locality::{InferenceTargetKind, resolve_inference_target};
use serde::Serialize;
use std::time::Duration;

/// Outcome of one doctor check.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "UPPERCASE")]
pub enum CheckResult {
    Pass,
    Warn,
    Fail,
    Skip,
}

impl CheckResult {
    pub fn label(self) -> &'static str {
        match self {
            Self::Pass => "PASS",
            Self::Warn => "WARN",
            Self::Fail => "FAIL",
            Self::Skip => "SKIP",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct DoctorCheck {
    pub area: &'static str,
    pub name: String,
    pub result: CheckResult,
    pub message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub hint: Option<String>,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize)]
pub struct DoctorSummary {
    pub pass: usize,
    pub warn: usize,
    pub fail: usize,
    pub skip: usize,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct DoctorReport {
    pub node: String,
    pub checks: Vec<DoctorCheck>,
    pub summary: DoctorSummary,
}

impl DoctorReport {
    fn new(node: &str, checks: Vec<DoctorCheck>) -> Self {
        let mut summary = DoctorSummary::default();
        for check in &checks {
            match check.result {
                CheckResult::Pass => summary.pass += 1,
                CheckResult::Warn => summary.warn += 1,
                CheckResult::Fail => summary.fail += 1,
                CheckResult::Skip => summary.skip += 1,
            }
        }
        Self {
            node: node.to_string(),
            checks,
            summary,
        }
    }

    pub fn find(&self, name: &str) -> Option<&DoctorCheck> {
        self.checks.iter().find(|check| check.name == name)
    }
}

fn check(
    area: &'static str,
    name: impl Into<String>,
    result: CheckResult,
    message: impl Into<String>,
) -> DoctorCheck {
    DoctorCheck {
        area,
        name: name.into(),
        result,
        message: message.into(),
        hint: None,
    }
}

fn with_hint(mut check: DoctorCheck, hint: impl Into<String>) -> DoctorCheck {
    check.hint = Some(hint.into());
    check
}

/// Observed Python interpreter.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PythonInfo {
    pub command: String,
    pub version: (u32, u32, u32),
    pub modules: Vec<(String, bool)>,
}

fn parse_python_version(output: &str) -> Option<(u32, u32, u32)> {
    let rest = output.trim().strip_prefix("Python ")?;
    let mut parts = rest
        .split(|c: char| !c.is_ascii_digit())
        .filter(|part| !part.is_empty())
        .map(|part| part.parse::<u32>().ok());
    Some((
        parts.next()??,
        parts.next()??,
        parts.next().flatten().unwrap_or(0),
    ))
}

async fn run_bounded(program: &str, args: &[&str]) -> Option<std::process::Output> {
    let child = tokio::process::Command::new(program)
        .args(args)
        .stdin(std::process::Stdio::null())
        .kill_on_drop(true)
        .output();
    tokio::time::timeout(Duration::from_secs(5), child)
        .await
        .ok()?
        .ok()
}

/// Find a Python interpreter and check optional modules without importing them.
pub async fn probe_python(modules: &[&str]) -> Option<PythonInfo> {
    let candidates: &[&str] = if cfg!(windows) {
        &["python", "py", "python3"]
    } else {
        &["python3", "python"]
    };
    for command in candidates {
        let Some(output) = run_bounded(command, &["--version"]).await else {
            continue;
        };
        let text = format!(
            "{}{}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
        let Some(version) = parse_python_version(&text) else {
            continue;
        };
        let mut found = Vec::new();
        for module in modules {
            // find_spec checks installation without executing the package.
            let script = format!(
                "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('{module}') else 1)"
            );
            let present = run_bounded(command, &["-c", &script])
                .await
                .is_some_and(|out| out.status.success());
            found.push(((*module).to_string(), present));
        }
        return Some(PythonInfo {
            command: (*command).to_string(),
            version,
            modules: found,
        });
    }
    None
}

fn runtime_checks(ctx: &RigContext, python: Option<&PythonInfo>) -> Vec<DoctorCheck> {
    let mut checks = vec![check(
        "runtime",
        "rain runtime",
        CheckResult::Pass,
        format!("rain {} · config loaded", env!("CARGO_PKG_VERSION")),
    )];
    let library = ctx.library_root.is_some();
    checks.push(match python {
        Some(info) if info.version >= (3, 10, 0) => check(
            "runtime",
            "python",
            CheckResult::Pass,
            format!(
                "{} → Python {}.{}.{}",
                info.command, info.version.0, info.version.1, info.version.2
            ),
        ),
        Some(info) => with_hint(
            check(
                "runtime",
                "python",
                if library {
                    CheckResult::Fail
                } else {
                    CheckResult::Warn
                },
                format!(
                    "Python {}.{}.{} is too old for R.A.I.N. Lab",
                    info.version.0, info.version.1, info.version.2
                ),
            ),
            "install Python 3.10+ (3.12 recommended)",
        ),
        None => with_hint(
            check(
                "runtime",
                "python",
                if library {
                    CheckResult::Fail
                } else {
                    CheckResult::Warn
                },
                "no Python interpreter found on PATH",
            ),
            "`python rain_lab.py` needs Python 3.10+ (3.12 recommended)",
        ),
    });
    checks.push(match &ctx.library_root {
        Some(root) => check(
            "runtime",
            "research library",
            CheckResult::Pass,
            root.display().to_string(),
        ),
        None => with_hint(
            check(
                "runtime",
                "research library",
                CheckResult::Warn,
                "not found from the current directory or the rain binary location",
            ),
            "run from the james_library checkout or pass --library <path>",
        ),
    });
    checks
}

fn state_dir_check(ctx: &RigContext) -> DoctorCheck {
    let state_dir = ctx.state_dir();
    let probe_dir = if state_dir.is_dir() {
        state_dir.clone()
    } else {
        ctx.config.workspace_dir.clone()
    };
    let probe = probe_dir.join(format!(".rig-write-check-{}", std::process::id()));
    let result = std::fs::write(&probe, b"ok").and_then(|()| std::fs::remove_file(&probe));
    match result {
        Ok(()) => check(
            "storage",
            "rig state",
            CheckResult::Pass,
            format!("writable ({})", state_dir.display()),
        ),
        Err(error) => with_hint(
            check(
                "storage",
                "rig state",
                CheckResult::Fail,
                format!("cannot write in {}: {error}", probe_dir.display()),
            ),
            "fix permissions on the R.A.I.N. workspace directory",
        ),
    }
}

fn find<'a>(status: &'a RigStatus, id: &str) -> Option<&'a CapabilityStatus> {
    status.get(id)
}

fn inference_checks(ctx: &RigContext, status: &RigStatus) -> Vec<DoctorCheck> {
    let mut checks = Vec::new();
    let preferred: Vec<String> = ctx
        .config
        .rig
        .profile
        .and_then(|kind| builtin_rig_profile(kind).ok())
        .map(|profile| profile.preferred_inference.clone())
        .unwrap_or_default();

    if let Some(selected) = status.selected_inference() {
        let detail = selected.inference.as_ref();
        let probed = detail.is_some_and(|d| d.probed);
        let result = match selected.state {
            CapabilityState::Running | CapabilityState::Available => CheckResult::Pass,
            CapabilityState::Configured if !probed => CheckResult::Pass,
            CapabilityState::Degraded => CheckResult::Warn,
            _ => CheckResult::Fail,
        };
        let mut item = check(
            "inference",
            "default provider",
            result,
            format!("{} · {}", selected.name, selected.detail),
        );
        if result == CheckResult::Fail && selected.id == "llamacpp" {
            item = with_hint(
                item,
                "start llama-server, e.g. `llama-server -m model.gguf --port 8080`",
            );
        }
        checks.push(item);

        if let (Some(model), Some(detail)) = (ctx.config.default_model.as_deref(), detail) {
            if selected.state == CapabilityState::Running && !detail.models.is_empty() {
                let served = detail.models.iter().any(|id| id == model);
                checks.push(if served {
                    check(
                        "inference",
                        "default model",
                        CheckResult::Pass,
                        format!("{model} is served"),
                    )
                } else {
                    with_hint(
                        check(
                            "inference",
                            "default model",
                            CheckResult::Warn,
                            format!("{model} is not in the server's model list"),
                        ),
                        format!(
                            "run `rain rig models`, then `rain models set <id>` (served: {})",
                            detail.models.join(", ")
                        ),
                    )
                });
            }
        }
    }

    for id in ["llamacpp", "ollama", "lmstudio"] {
        let Some(cap) = find(status, id) else {
            continue;
        };
        let selected = cap.inference.as_ref().is_some_and(|d| d.selected);
        if selected {
            continue; // covered by "default provider"
        }
        let result = match cap.state {
            CapabilityState::Running => CheckResult::Pass,
            CapabilityState::Degraded => CheckResult::Warn,
            _ => CheckResult::Skip,
        };
        checks.push(check(
            "inference",
            cap.name.clone(),
            result,
            cap.detail.clone(),
        ));
    }

    if !preferred.is_empty() {
        let running: Vec<&str> = preferred
            .iter()
            .filter_map(|id| find(status, id))
            .filter(|cap| cap.state == CapabilityState::Running)
            .map(|cap| cap.name.as_str())
            .collect();
        checks.push(if running.is_empty() {
            with_hint(
                check(
                    "inference",
                    "profile inference",
                    CheckResult::Warn,
                    format!(
                        "none of the profile's preferred servers is running ({})",
                        preferred.join(", ")
                    ),
                ),
                "start llama-server, `ollama serve`, or the LM Studio server",
            )
        } else {
            check(
                "inference",
                "profile inference",
                CheckResult::Pass,
                format!("running: {}", running.join(", ")),
            )
        });
    }

    let local_models: usize = status
        .in_category(CapabilityCategory::Inference)
        .filter(|cap| cap.state == CapabilityState::Running)
        .filter_map(|cap| cap.inference.as_ref())
        .filter(|detail| detail.locality != "remote")
        .map(|detail| detail.models.len())
        .sum();
    let any_local_running = status
        .in_category(CapabilityCategory::Inference)
        .any(|cap| cap.state == CapabilityState::Running);
    checks.push(match (any_local_running, local_models) {
        (false, _) => check(
            "inference",
            "local model discovery",
            if status.privacy.mode == RigPrivacyMode::Local {
                CheckResult::Warn
            } else {
                CheckResult::Skip
            },
            "no local inference server is running",
        ),
        (true, 0) => with_hint(
            check(
                "inference",
                "local model discovery",
                CheckResult::Warn,
                "a local server is running but reports no models",
            ),
            "load a model (llama-server -m, `ollama pull`, or LM Studio)",
        ),
        (true, count) => check(
            "inference",
            "local model discovery",
            CheckResult::Pass,
            format!("{count} local model(s) discovered"),
        ),
    });
    checks
}

fn privacy_checks(ctx: &RigContext, status: &RigStatus) -> Vec<DoctorCheck> {
    let privacy = &status.privacy;
    let local = privacy.mode == RigPrivacyMode::Local;
    let mut checks = vec![check(
        "privacy",
        "privacy mode",
        CheckResult::Pass,
        format!(
            "{} ({}; {})",
            privacy.mode,
            privacy.mode.label(),
            match privacy.source {
                crate::config::RigPrivacySource::Explicit => "set in [rig]",
                crate::config::RigPrivacySource::Profile => "from profile",
                crate::config::RigPrivacySource::Default => "default, pre-Rig behavior",
            }
        ),
    )];
    for violation in &privacy.violations {
        checks.push(with_hint(
            check(
                "privacy",
                "hosted inference",
                CheckResult::Fail,
                violation.clone(),
            ),
            "switch to llama.cpp/Ollama/LM Studio or set [rig] privacy = \"hybrid\"",
        ));
    }

    // Self-hosted providers pointed at a remote host.
    let provider = super::context::selected_provider(&ctx.config);
    let target = resolve_inference_target(&provider, ctx.config.api_url.as_deref());
    if target.kind == InferenceTargetKind::Endpoint && !target.locality.is_local() && !local {
        checks.push(check(
            "privacy",
            "non-local endpoint",
            CheckResult::Warn,
            format!(
                "default provider {} uses a remote endpoint (api_url)",
                crate::providers::locality::display_provider_id(&provider)
            ),
        ));
    }

    let meeting = MeetingInference::from_context(ctx);
    let sources = format!(
        "endpoint from {}, model from {}",
        meeting.base_url_source.label(),
        meeting.model_source.label()
    );
    if meeting.is_hosted() {
        let what = if meeting.hosted_model {
            format!(
                "meeting model {} is an Ollama cloud model (hosted; {sources})",
                meeting.model
            )
        } else {
            format!("meeting endpoint is not local ({sources})")
        };
        checks.push(with_hint(
            check(
                "privacy",
                "meeting inference",
                if local { CheckResult::Fail } else { CheckResult::Warn },
                what,
            ),
            if local {
                "the meeting will refuse to start under local privacy; run `rain rig setup` to pin [rig.meeting] to a running local server, or set RAIN_LLM_MODEL"
            } else {
                "run `rain rig setup` or set [rig.meeting] model to keep meeting prompts local"
            },
        ));
    } else {
        let mut item = check(
            "privacy",
            "meeting inference",
            CheckResult::Pass,
            format!(
                "model {} · endpoint {} ({sources})",
                meeting.model,
                meeting.endpoint_locality.label()
            ),
        );
        if meeting.uses_environment() {
            item = with_hint(
                item,
                "value comes from this shell's environment; persist it with [rig.meeting] so every shell agrees",
            );
        }
        checks.push(item);
    }

    if let Some(jev) = find(status, "jev") {
        if jev.state != CapabilityState::Disabled && local {
            checks.push(check(
                "privacy",
                "remote judgment",
                CheckResult::Warn,
                "Jev (TypeSafe) is enabled; requests leave this machine with per-request consent",
            ));
        }
    }
    checks.push(check(
        "privacy",
        "external services",
        if privacy.external_services.is_empty() {
            CheckResult::Pass
        } else {
            CheckResult::Warn
        },
        if privacy.external_services.is_empty() {
            "none configured".to_string()
        } else {
            privacy
                .external_services
                .iter()
                .map(|service| service.name.clone())
                .collect::<Vec<_>>()
                .join(", ")
        },
    ));
    checks
}

async fn network_checks(ctx: &RigContext, status: &RigStatus) -> Vec<DoctorCheck> {
    let mut checks = Vec::new();
    for listener in &status.network.listeners {
        let name = format!("{} bind", listener.component);
        let summary = format!(
            "{}:{} ({})",
            listener.host,
            listener.port,
            listener.exposure.label()
        );
        checks.push(match (listener.exposure, listener.explicitly_allowed) {
            (BindExposure::Loopback, _) => check("network", name, CheckResult::Pass, summary),
            (_, true) => with_hint(
                check(
                    "network",
                    name,
                    CheckResult::Warn,
                    format!("EXTERNAL BIND {summary}"),
                ),
                "keep require_pairing on; bind 127.0.0.1 unless remote access is intended",
            ),
            (_, false) => with_hint(
                check(
                    "network",
                    name,
                    CheckResult::Fail,
                    format!("EXTERNAL BIND {summary} is not allowed"),
                ),
                "set [gateway] host = \"127.0.0.1\" (or allow_public_bind = true deliberately)",
            ),
        });
    }

    let port = ctx.config.gateway.port;
    let gateway = find(status, "gateway");
    let gateway_running = gateway.is_some_and(|g| g.state == CapabilityState::Running);
    let inference_ports: &[(u16, &str)] =
        &[(8080, "llama.cpp"), (11434, "Ollama"), (1234, "LM Studio")];
    let conflict = inference_ports.iter().find(|(p, _)| *p == port);
    let port_open = ctx.probe.tcp_open("127.0.0.1", port).await;
    checks.push(match (conflict, gateway_running, port_open) {
        (Some((_, server)), _, _) => with_hint(
            check(
                "network",
                "port conflicts",
                CheckResult::Warn,
                format!("gateway.port {port} is the default {server} port"),
            ),
            "choose another [gateway] port",
        ),
        (None, false, true) => with_hint(
            check(
                "network",
                "port conflicts",
                CheckResult::Warn,
                format!("port {port} is in use, but not by a R.A.I.N. gateway"),
            ),
            "stop the other service or change [gateway] port",
        ),
        _ => check(
            "network",
            "port conflicts",
            CheckResult::Pass,
            format!("gateway port {port} is free or held by R.A.I.N."),
        ),
    });
    checks
}

fn skybridge_self_test() -> Result<String, String> {
    use super::skybridge::{frame, modem};
    let config = modem::ModemConfig::default();
    let station = frame::StationId::parse("TEST").map_err(|e| e.to_string())?;
    let original =
        frame::Frame::new(station, 1, b"skybridge self-test").map_err(|e| e.to_string())?;
    let bytes = original.encode().map_err(|e| e.to_string())?;
    let samples = modem::modulate(&config, &bytes).map_err(|e| e.to_string())?;
    let decoded = modem::demodulate(&config, &samples).map_err(|e| e.to_string())?;
    if decoded == original {
        Ok(format!(
            "baseband round trip OK ({} baud, {} Hz)",
            config.baud, config.sample_rate
        ))
    } else {
        Err("decoded frame differs from the original".into())
    }
}

fn transport_checks(
    ctx: &RigContext,
    status: &RigStatus,
    python: Option<&PythonInfo>,
) -> Vec<DoctorCheck> {
    let wanted: Vec<String> = ctx
        .config
        .rig
        .profile
        .and_then(|kind| builtin_rig_profile(kind).ok())
        .map(|profile| profile.wanted_capabilities.clone())
        .unwrap_or_default();
    let module = |name: &str| -> Option<bool> {
        python.and_then(|info| {
            info.modules
                .iter()
                .find(|(module, _)| module == name)
                .map(|(_, present)| *present)
        })
    };
    let mut checks = Vec::new();
    for (id, module_name, install) in [
        ("reticulum", "RNS", "pip install rns"),
        ("lxmf", "LXMF", "pip install lxmf"),
    ] {
        let Some(cap) = find(status, id) else {
            continue;
        };
        let is_wanted = wanted.iter().any(|w| w == id);
        let module_note = match module(module_name) {
            Some(true) => format!(" · python module {module_name} installed"),
            Some(false) => format!(" · python module {module_name} missing"),
            None => String::new(),
        };
        let result = match cap.state {
            CapabilityState::Running => CheckResult::Pass,
            CapabilityState::Configured => CheckResult::Warn,
            _ if is_wanted => CheckResult::Warn,
            _ => CheckResult::Skip,
        };
        let mut item = check(
            "transports",
            cap.name.clone(),
            result,
            format!("{}{module_note}", cap.detail),
        );
        if result == CheckResult::Warn && cap.state == CapabilityState::Unavailable {
            item = with_hint(item, format!("optional: {install}"));
        }
        checks.push(item);
    }
    checks.push(match skybridge_self_test() {
        Ok(message) => check(
            "transports",
            "Skybridge (experimental)",
            CheckResult::Pass,
            message,
        ),
        Err(error) => check(
            "transports",
            "Skybridge (experimental)",
            CheckResult::Fail,
            error,
        ),
    });
    let rf = super::skybridge::radio::active_backend();
    checks.push(check(
        "transports",
        "RF transmit",
        if rf.can_transmit() {
            CheckResult::Fail
        } else {
            CheckResult::Pass
        },
        format!("backend '{}' · transmit disabled", rf.name()),
    ));
    checks
}

fn decision_checks(status: &RigStatus) -> Vec<DoctorCheck> {
    ["deterministic-validation", "laya", "jev"]
        .iter()
        .filter_map(|id| find(status, id))
        .map(|cap| {
            let result = match cap.state {
                CapabilityState::Available
                | CapabilityState::Running
                | CapabilityState::Configured => CheckResult::Pass,
                CapabilityState::Disabled | CapabilityState::Unavailable => CheckResult::Skip,
                CapabilityState::Degraded => CheckResult::Warn,
            };
            check("decision", cap.name.clone(), result, cap.detail.clone())
        })
        .collect()
}

fn research_checks(status: &RigStatus) -> Vec<DoctorCheck> {
    let personas: Vec<&CapabilityStatus> = ["james", "jasmine", "luca", "elena"]
        .iter()
        .filter_map(|id| find(status, id))
        .collect();
    let missing: Vec<&str> = personas
        .iter()
        .filter(|cap| !cap.state.is_usable())
        .map(|cap| cap.name.as_str())
        .collect();
    let mut checks = vec![if !status.runtime.library_found {
        check(
            "research",
            "personas",
            CheckResult::Skip,
            "research library not found",
        )
    } else if missing.is_empty() {
        check(
            "research",
            "personas",
            CheckResult::Pass,
            "James, Jasmine, Luca, Elena",
        )
    } else {
        check(
            "research",
            "personas",
            CheckResult::Fail,
            format!("missing: {}", missing.join(", ")),
        )
    }];
    if let Some(registry) = find(status, "research-registry") {
        checks.push(check(
            "research",
            "papers corpus",
            match (status.runtime.library_found, registry.state.is_usable()) {
                (false, _) => CheckResult::Skip,
                (true, true) => CheckResult::Pass,
                (true, false) => CheckResult::Warn,
            },
            registry.detail.clone(),
        ));
    }
    if let Some(meeting) = find(status, "lab-meeting") {
        checks.push(check(
            "research",
            "meeting endpoint",
            match meeting.state {
                CapabilityState::Running => CheckResult::Pass,
                _ => CheckResult::Skip,
            },
            meeting.detail.clone(),
        ));
    }
    checks
}

/// Run every check.
pub async fn run(ctx: &RigContext) -> DoctorReport {
    let (status, python) = tokio::join!(collect(ctx), probe_python(&["RNS", "LXMF"]));
    let mut checks = runtime_checks(ctx, python.as_ref());
    checks.push(state_dir_check(ctx));
    checks.extend(research_checks(&status));
    checks.extend(inference_checks(ctx, &status));
    checks.extend(privacy_checks(ctx, &status));
    checks.extend(network_checks(ctx, &status).await);
    checks.extend(decision_checks(&status));
    checks.extend(transport_checks(ctx, &status, python.as_ref()));
    DoctorReport::new(&status.identity.node, checks)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::rig::test_support::{context, write_library};

    #[test]
    fn parses_python_versions() {
        assert_eq!(parse_python_version("Python 3.11.15\n"), Some((3, 11, 15)));
        assert_eq!(parse_python_version("Python 3.12"), Some((3, 12, 0)));
        assert_eq!(parse_python_version("Python 3.13.0rc1"), Some((3, 13, 0)));
        assert_eq!(parse_python_version("pyenv: not found"), None);
    }

    #[test]
    fn skybridge_self_test_passes() {
        assert!(skybridge_self_test().is_ok());
    }

    #[tokio::test]
    async fn missing_optional_extensions_are_skip_not_fail() {
        let ctx = context();
        let status = collect(&ctx).await;
        let checks = transport_checks(&ctx, &status, None);
        for check in &checks {
            if matches!(check.name.as_str(), "Reticulum" | "LXMF")
                && status
                    .get(&check.name.to_ascii_lowercase())
                    .is_some_and(|c| c.state == CapabilityState::Unavailable)
            {
                assert_eq!(check.result, CheckResult::Skip, "{check:?}");
            }
            assert_ne!(check.result, CheckResult::Fail, "{check:?}");
        }
        let unwanted_inference = inference_checks(&ctx, &status);
        let llamacpp = unwanted_inference
            .iter()
            .find(|c| c.name == "llama.cpp")
            .unwrap();
        assert_eq!(llamacpp.result, CheckResult::Skip);
    }

    #[tokio::test]
    async fn profile_wanted_transport_missing_is_warn() {
        let mut ctx = context();
        ctx.config.rig.profile = Some(crate::config::RigProfileKind::Field);
        let mut status = collect(&ctx).await;
        for cap in &mut status.capabilities {
            if cap.id == "reticulum" {
                cap.state = CapabilityState::Unavailable;
            }
        }
        let checks = transport_checks(&ctx, &status, None);
        let reticulum = checks.iter().find(|c| c.name == "Reticulum").unwrap();
        assert_eq!(reticulum.result, CheckResult::Warn);
    }

    #[tokio::test]
    async fn unreachable_default_llamacpp_fails_with_hint() {
        let mut ctx = context();
        ctx.config.default_provider = Some("llamacpp".into());
        let report = run(&ctx).await;
        let default = report.find("default provider").unwrap();
        assert_eq!(default.result, CheckResult::Fail);
        assert!(default.hint.as_deref().unwrap().contains("llama-server"));
        assert!(report.summary.fail >= 1);
    }

    #[tokio::test]
    async fn local_privacy_with_hosted_provider_fails() {
        let mut ctx = context();
        ctx.config.rig.privacy = Some(RigPrivacyMode::Local);
        ctx.config.default_provider = Some("openrouter".into());
        let report = run(&ctx).await;
        assert!(
            report
                .checks
                .iter()
                .any(|c| c.name == "hosted inference" && c.result == CheckResult::Fail)
        );
    }

    #[tokio::test]
    async fn external_bind_is_reported_prominently() {
        let mut ctx = context();
        ctx.config.gateway.host = "0.0.0.0".into();
        ctx.config.gateway.allow_public_bind = true;
        let status = collect(&ctx).await;
        let checks = network_checks(&ctx, &status).await;
        let bind = checks.iter().find(|c| c.name == "gateway bind").unwrap();
        assert_eq!(bind.result, CheckResult::Warn);
        assert!(bind.message.contains("EXTERNAL BIND"));
    }

    #[tokio::test]
    async fn gateway_port_colliding_with_llamacpp_default_warns() {
        let mut ctx = context();
        ctx.config.gateway.port = 8080;
        let status = collect(&ctx).await;
        let checks = network_checks(&ctx, &status).await;
        let conflict = checks.iter().find(|c| c.name == "port conflicts").unwrap();
        assert_eq!(conflict.result, CheckResult::Warn);
    }

    #[tokio::test]
    async fn state_dir_write_check_and_library_checks() {
        let dir = tempfile::tempdir().unwrap();
        let mut ctx = context();
        ctx.config.workspace_dir = dir.path().to_path_buf();
        assert_eq!(state_dir_check(&ctx).result, CheckResult::Pass);
        assert!(
            !dir.path().join("rig").exists(),
            "doctor must not create state dirs"
        );

        let library = tempfile::tempdir().unwrap();
        write_library(library.path());
        ctx.library_root = Some(library.path().to_path_buf());
        let status = collect(&ctx).await;
        let research = research_checks(&status);
        assert_eq!(research[0].result, CheckResult::Pass);
    }

    #[test]
    fn report_summary_counts_results() {
        let report = DoctorReport::new(
            "rain-local",
            vec![
                check("a", "1", CheckResult::Pass, ""),
                check("a", "2", CheckResult::Warn, ""),
                check("a", "3", CheckResult::Skip, ""),
                check("a", "4", CheckResult::Fail, ""),
            ],
        );
        assert_eq!(
            report.summary,
            DoctorSummary {
                pass: 1,
                warn: 1,
                fail: 1,
                skip: 1
            }
        );
        let json = serde_json::to_value(&report).unwrap();
        assert_eq!(json["checks"][0]["result"], "PASS");
    }
}
