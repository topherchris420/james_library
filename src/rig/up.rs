//! `rain rig up`: preflight the node, then start the services R.A.I.N.
//! owns — its daemon (gateway, configured channels, heartbeat, scheduler) on
//! the configured bind (loopback by default) and, when `[rig.bridge]` is
//! enabled, the Reticulum/LXMF bridge sidecar on `127.0.0.1`.
//!
//! It never starts third-party servers (llama.cpp, Ollama, LM Studio,
//! rnsd), downloads models, installs packages, or changes bind policy: the
//! gateway's own `allow_public_bind` enforcement still applies. A blocked
//! node (policy contradiction) is refused before anything starts. The bridge
//! runs as a child process: it stops with `rig up`, and if it exits early
//! `rig up` reports it instead of restarting it in a loop.

use super::capability::{CapabilityCategory, CapabilityState};
use super::context::RigContext;
use super::status::{NodeReadiness, RigStatus, collect};
use super::transport::bridge::BridgeClient;
use super::transport::discovery::{BridgeObservation, configured_bridge, observe_bridge};
use crate::config::Config;
use anyhow::{Context, Result, bail};
use std::fmt::Write as _;
use std::path::{Path, PathBuf};
use std::time::Duration;

/// Bridge script, relative to the research library root.
pub const BRIDGE_SCRIPT: &str = "tools/rig_bridge/bridge.py";
/// Optional Python dependencies of the sidecar.
const BRIDGE_SCRIPT_REQUIREMENTS: &str = "tools/rig_bridge/requirements.txt";
/// Exit code the sidecar uses when Reticulum/LXMF are not installed.
const BRIDGE_EXIT_MISSING_DEPENDENCY: i32 = 3;
const BRIDGE_READY_TIMEOUT: Duration = Duration::from_secs(20);

/// What `rig up` will do.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum UpAction {
    /// The gateway already answers on the configured port.
    AlreadyRunning,
    /// Start the daemon on `host:port`.
    StartDaemon { host: String, port: u16 },
}

/// What `rig up` does with the bridge sidecar.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum BridgeAction {
    /// `[rig.bridge]` is absent or disabled.
    Disabled,
    /// An authenticated bridge already answers.
    AlreadyRunning { endpoint: String },
    /// Start the sidecar.
    Start(BridgeLaunch),
}

/// Exact command line for the sidecar (argv only, no shell).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BridgeLaunch {
    pub program: PathBuf,
    pub args: Vec<String>,
    pub endpoint: String,
}

/// Python interpreter: the library's virtualenv when present, else the
/// platform's `python3`/`python` on `PATH`.
fn python_for(library: &Path) -> PathBuf {
    let venv = if cfg!(windows) {
        library.join(".venv").join("Scripts").join("python.exe")
    } else {
        library.join(".venv").join("bin").join("python")
    };
    if venv.is_file() {
        venv
    } else if cfg!(windows) {
        PathBuf::from("python")
    } else {
        PathBuf::from("python3")
    }
}

/// Decide what to do with the bridge (pure; unit-tested).
pub fn bridge_plan(ctx: &RigContext, observed: &BridgeObservation) -> Result<BridgeAction> {
    let Some(settings) = ctx.config.rig.enabled_bridge() else {
        return Ok(BridgeAction::Disabled);
    };
    match observed {
        BridgeObservation::Disabled => Ok(BridgeAction::Disabled),
        BridgeObservation::Connected { endpoint, .. } => Ok(BridgeAction::AlreadyRunning {
            endpoint: endpoint.clone(),
        }),
        BridgeObservation::Unreachable { endpoint, .. } => {
            let Some(library) = ctx.library_root.as_deref() else {
                bail!(
                    "[rig.bridge] is enabled but the research library was not found; run from the James Library checkout or pass --library"
                );
            };
            let script = library.join(BRIDGE_SCRIPT);
            if !script.is_file() {
                bail!("bridge sidecar not found at {}", script.display());
            }
            let mut args = vec![
                script.display().to_string(),
                "--state-dir".into(),
                ctx.state_dir().display().to_string(),
                "--port".into(),
                settings.port.to_string(),
                "--name".into(),
                ctx.config.rig.node_name().to_string(),
            ];
            if settings.announce {
                args.push("--announce".into());
            }
            Ok(BridgeAction::Start(BridgeLaunch {
                program: python_for(library),
                args,
                endpoint: endpoint.clone(),
            }))
        }
    }
}

fn describe_bridge(action: &BridgeAction, announce: bool) -> String {
    match action {
        BridgeAction::Disabled => String::new(),
        BridgeAction::AlreadyRunning { endpoint } => {
            format!("\nReticulum/LXMF bridge: already running on {endpoint}; nothing to start.\n")
        }
        BridgeAction::Start(launch) => format!(
            "\nReticulum/LXMF bridge: start {BRIDGE_SCRIPT} on {} (loopback only; announce {}).\n",
            launch.endpoint,
            if announce { "on" } else { "off" }
        ),
    }
}

/// Start the sidecar and wait until an authenticated session succeeds.
pub async fn start_bridge(
    launch: &BridgeLaunch,
    client: &BridgeClient,
) -> Result<tokio::process::Child> {
    let mut child = tokio::process::Command::new(&launch.program)
        .args(&launch.args)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .kill_on_drop(true)
        .spawn()
        .with_context(|| format!("starting the bridge with {}", launch.program.display()))?;
    let deadline = tokio::time::Instant::now() + BRIDGE_READY_TIMEOUT;
    loop {
        if let Some(status) = child.try_wait()? {
            if status.code() == Some(BRIDGE_EXIT_MISSING_DEPENDENCY) {
                bail!(
                    "the bridge needs Reticulum and LXMF: pip install -r {BRIDGE_SCRIPT_REQUIREMENTS}"
                );
            }
            bail!("the bridge exited before it was ready ({status})");
        }
        if client.connect().await.is_ok() {
            return Ok(child);
        }
        if tokio::time::Instant::now() >= deadline {
            bail!(
                "the bridge did not become ready on {} within {}s",
                launch.endpoint,
                BRIDGE_READY_TIMEOUT.as_secs()
            );
        }
        tokio::time::sleep(Duration::from_millis(250)).await;
    }
}

/// Decide the action and describe the plan (pure; unit-tested).
pub fn plan(config: &Config, status: &RigStatus) -> Result<(UpAction, String)> {
    let mut text = String::new();
    let _ = writeln!(text, "R.A.I.N. RIG UP // NODE {}\n", status.identity.node);
    if status.readiness == NodeReadiness::Blocked {
        let mut message = String::from("node is BLOCKED; nothing was started:");
        for reason in &status.reasons {
            let _ = write!(message, "\n  - {reason}");
        }
        bail!(message);
    }

    let _ = writeln!(text, "Inference (not managed by R.A.I.N.):");
    for cap in status.in_category(CapabilityCategory::Inference) {
        let Some(detail) = cap.inference.as_ref() else {
            continue;
        };
        let role = if detail.selected {
            " (default provider)"
        } else {
            ""
        };
        let _ = writeln!(
            text,
            "  {} {}{role}: {}",
            cap.state.glyph(),
            cap.name,
            cap.detail
        );
    }

    let gateway = status.get("gateway");
    let listener = status
        .network
        .listeners
        .iter()
        .find(|listener| listener.component == "gateway");
    let (host, port) = (config.gateway.host.clone(), config.gateway.port);
    let action = if gateway.is_some_and(|cap| cap.state == CapabilityState::Running) {
        let _ = writeln!(
            text,
            "\nR.A.I.N. daemon: already running on {host}:{port}; nothing to start."
        );
        UpAction::AlreadyRunning
    } else {
        let exposure = listener.map_or("unknown", |l| l.exposure.label());
        let _ = writeln!(
            text,
            "\nR.A.I.N. daemon: start in the foreground on {host}:{port} ({exposure})."
        );
        if listener.is_some_and(|l| !l.exposure.is_loopback()) {
            let _ = writeln!(
                text,
                "  ⚠ EXTERNAL BIND: this listener is reachable beyond this machine (allowed by config)."
            );
        }
        UpAction::StartDaemon { host, port }
    };
    if status.readiness == NodeReadiness::Degraded {
        let _ = writeln!(text, "\nNode is DEGRADED:");
        for reason in &status.reasons {
            let _ = writeln!(text, "  - {reason}");
        }
    }
    Ok((action, text))
}

pub async fn run(config: Config, ctx: &RigContext, dry_run: bool) -> Result<()> {
    let status = collect(ctx).await;
    let (action, text) = plan(&config, &status)?;
    let bridge_client = configured_bridge(ctx);
    let bridge_action = bridge_plan(ctx, &observe_bridge(bridge_client.as_ref()).await)?;
    let announce = ctx.config.rig.enabled_bridge().is_some_and(|b| b.announce);
    print!("{text}{}", describe_bridge(&bridge_action, announce));
    let starts_something = matches!(action, UpAction::StartDaemon { .. })
        || matches!(bridge_action, BridgeAction::Start(_));
    if dry_run {
        if starts_something {
            println!("\nDry run: nothing started.");
        }
        return Ok(());
    }

    let mut bridge_child = match (&bridge_action, &bridge_client) {
        (BridgeAction::Start(launch), Some(client)) => {
            let child = start_bridge(launch, client).await?;
            println!("Bridge ready on {}.", launch.endpoint);
            Some(child)
        }
        _ => None,
    };

    match (action, bridge_child.as_mut()) {
        (UpAction::StartDaemon { host, port }, Some(child)) => {
            println!("\nStarting daemon (Ctrl-C to stop the daemon and the bridge)…");
            let mut daemon = Box::pin(crate::daemon::run(config, host, port));
            tokio::select! {
                result = &mut daemon => result,
                exit = child.wait() => {
                    tracing::warn!("rig bridge exited ({}); the daemon keeps running without it", exit.map_or_else(|e| e.to_string(), |s| s.to_string()));
                    daemon.await
                }
            }
        }
        (UpAction::StartDaemon { host, port }, None) => {
            println!("\nStarting daemon (Ctrl-C to stop)…");
            Box::pin(crate::daemon::run(config, host, port)).await
        }
        (UpAction::AlreadyRunning, Some(child)) => {
            println!("\nBridge running in the foreground (Ctrl-C to stop).");
            tokio::select! {
                exit = child.wait() => bail!("the bridge exited ({})", exit?),
                signal = tokio::signal::ctrl_c() => signal.map_err(Into::into),
            }
        }
        (UpAction::AlreadyRunning, None) => Ok(()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::rig::test_support::context;

    #[tokio::test]
    async fn blocked_node_starts_nothing() {
        let mut ctx = context();
        ctx.config.rig.privacy = Some(crate::config::RigPrivacyMode::Local);
        ctx.config.default_provider = Some("openrouter".into());
        let status = collect(&ctx).await;
        let error = plan(&ctx.config, &status).unwrap_err().to_string();
        assert!(error.contains("BLOCKED"), "{error}");
    }

    #[tokio::test]
    async fn default_plan_starts_loopback_daemon() {
        let ctx = context();
        let status = collect(&ctx).await;
        let (action, text) = plan(&ctx.config, &status).unwrap();
        assert_eq!(
            action,
            UpAction::StartDaemon {
                host: "127.0.0.1".into(),
                port: ctx.config.gateway.port
            }
        );
        assert!(text.contains("loopback only"), "{text}");
        assert!(text.contains("not managed by R.A.I.N."));
    }

    fn bridge_context(announce: bool) -> (RigContext, tempfile::TempDir) {
        let library = tempfile::tempdir().unwrap();
        std::fs::write(library.path().join("rain_lab.py"), "").unwrap();
        std::fs::write(library.path().join("JAMES_SOUL.md"), "# James").unwrap();
        std::fs::create_dir_all(library.path().join("tools/rig_bridge")).unwrap();
        std::fs::write(library.path().join(BRIDGE_SCRIPT), "").unwrap();
        let mut ctx = context();
        ctx.library_root = Some(library.path().to_path_buf());
        ctx.config.workspace_dir = library.path().join("workspace");
        ctx.config.rig.bridge = Some(crate::config::RigBridgeConfig {
            enabled: true,
            port: 42999,
            announce,
        });
        (ctx, library)
    }

    fn unreachable() -> BridgeObservation {
        BridgeObservation::Unreachable {
            endpoint: "127.0.0.1:42999".into(),
            error: "refused".into(),
        }
    }

    #[test]
    fn bridge_plan_is_off_unless_enabled() {
        let ctx = context();
        assert_eq!(
            bridge_plan(&ctx, &unreachable()).unwrap(),
            BridgeAction::Disabled
        );
    }

    #[test]
    fn bridge_plan_starts_loopback_sidecar_with_argv_only() {
        let (ctx, _library) = bridge_context(false);
        let BridgeAction::Start(launch) = bridge_plan(&ctx, &unreachable()).unwrap() else {
            panic!("expected a start");
        };
        assert!(launch.args[0].ends_with(BRIDGE_SCRIPT));
        assert!(launch.args.windows(2).any(|w| w == ["--port", "42999"]));
        assert!(
            !launch
                .args
                .iter()
                .any(|a| a == "--announce" || a.contains("host"))
        );
        let (announcing, _library) = bridge_context(true);
        let BridgeAction::Start(launch) = bridge_plan(&announcing, &unreachable()).unwrap() else {
            panic!("expected a start");
        };
        assert!(launch.args.iter().any(|a| a == "--announce"));
        let connected = BridgeObservation::Connected {
            endpoint: "127.0.0.1:42999".into(),
            status: crate::rig::transport::bridge::BridgeStatus::default(),
        };
        assert!(matches!(
            bridge_plan(&ctx, &connected).unwrap(),
            BridgeAction::AlreadyRunning { .. }
        ));
    }

    #[test]
    fn bridge_plan_without_library_fails_before_starting_anything() {
        let (mut ctx, _library) = bridge_context(false);
        ctx.library_root = None;
        assert!(bridge_plan(&ctx, &unreachable()).is_err());
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn missing_reticulum_is_reported_not_retried() {
        use std::os::unix::fs::PermissionsExt;
        let (ctx, library) = bridge_context(false);
        let python = library.path().join(".venv/bin/python");
        std::fs::create_dir_all(python.parent().unwrap()).unwrap();
        std::fs::write(&python, "#!/bin/sh\nexit 3\n").unwrap();
        std::fs::set_permissions(&python, std::fs::Permissions::from_mode(0o755)).unwrap();
        let BridgeAction::Start(launch) = bridge_plan(&ctx, &unreachable()).unwrap() else {
            panic!("expected a start");
        };
        assert_eq!(launch.program, python);
        let client = configured_bridge(&ctx).unwrap();
        let error = start_bridge(&launch, &client)
            .await
            .unwrap_err()
            .to_string();
        assert!(error.contains("requirements.txt"), "{error}");
    }

    #[tokio::test]
    async fn dry_run_does_not_start_anything() {
        let ctx = context();
        Box::pin(run(ctx.config.clone(), &ctx, true)).await.unwrap();
        let port = ctx.config.gateway.port;
        assert!(!ctx.probe.tcp_open("127.0.0.1", port).await);
    }
}
