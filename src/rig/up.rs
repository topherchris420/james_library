//! `rain rig up`: preflight the node, then start the one service R.A.I.N.
//! owns — its daemon (gateway, configured channels, heartbeat, scheduler) —
//! on the configured bind, which is loopback by default.
//!
//! It never starts third-party servers (llama.cpp, Ollama, LM Studio,
//! rnsd), downloads models, or changes bind policy: the gateway's own
//! `allow_public_bind` enforcement still applies. A blocked node (policy
//! contradiction) is refused before anything starts.

use super::capability::{CapabilityCategory, CapabilityState};
use super::context::RigContext;
use super::status::{NodeReadiness, RigStatus, collect};
use crate::config::Config;
use anyhow::{Result, bail};
use std::fmt::Write as _;

/// What `rig up` will do.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum UpAction {
    /// The gateway already answers on the configured port.
    AlreadyRunning,
    /// Start the daemon on `host:port`.
    StartDaemon { host: String, port: u16 },
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
    print!("{text}");
    match action {
        UpAction::AlreadyRunning => Ok(()),
        UpAction::StartDaemon { .. } if dry_run => {
            println!("\nDry run: nothing started.");
            Ok(())
        }
        UpAction::StartDaemon { host, port } => {
            println!("\nStarting daemon (Ctrl-C to stop)…");
            Box::pin(crate::daemon::run(config, host, port)).await
        }
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

    #[tokio::test]
    async fn dry_run_does_not_start_anything() {
        let ctx = context();
        Box::pin(run(ctx.config.clone(), &ctx, true)).await.unwrap();
        let port = ctx.config.gateway.port;
        assert!(!ctx.probe.tcp_open("127.0.0.1", port).await);
    }
}
