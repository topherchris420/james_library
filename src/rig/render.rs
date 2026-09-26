//! Human-readable output for `rain rig` commands. Every renderer returns a
//! `String` so output is testable; `--json` bypasses this module entirely.

use super::capability::{CapabilityCategory, CapabilityState, CapabilityStatus};
use super::doctor::{CheckResult, DoctorReport};
use super::status::{NodeReadiness, RigStatus};
use console::style;
use std::fmt::Write;

const MAX_LISTED_MODELS: usize = 8;

fn glyph(state: CapabilityState) -> String {
    let symbol = state.glyph();
    if state.is_usable() {
        style(symbol).green().to_string()
    } else if state == CapabilityState::Degraded {
        style(symbol).yellow().to_string()
    } else {
        style(symbol).dim().to_string()
    }
}

fn heading(out: &mut String, title: &str) {
    let _ = writeln!(out, "\n{}", style(title).bold());
}

fn line(out: &mut String, cap: &CapabilityStatus) {
    let tag = if cap.experimental {
        " [experimental]"
    } else {
        ""
    };
    let _ = writeln!(
        out,
        "  {} {:<26} {:<12} {}",
        glyph(cap.state),
        format!("{}{tag}", cap.name),
        cap.state.as_str(),
        cap.detail
    );
}

fn model_list(models: &[String]) -> String {
    if models.is_empty() {
        return "none listed".into();
    }
    let mut shown: Vec<&str> = models
        .iter()
        .take(MAX_LISTED_MODELS)
        .map(String::as_str)
        .collect();
    if models.len() > MAX_LISTED_MODELS {
        shown.push("…");
    }
    shown.join(", ")
}

fn inference_block(out: &mut String, cap: &CapabilityStatus) {
    let Some(detail) = cap.inference.as_ref() else {
        line(out, cap);
        return;
    };
    let expanded = cap.state == CapabilityState::Running || detail.selected;
    if !expanded {
        line(out, cap);
        return;
    }
    let _ = writeln!(
        out,
        "  {} {:<26} {}",
        glyph(cap.state),
        cap.name,
        cap.state.as_str()
    );
    if let Some(endpoint) = &detail.endpoint {
        let _ = writeln!(out, "      endpoint    {endpoint}");
    }
    if cap.state == CapabilityState::Running {
        let _ = writeln!(out, "      models      {}", model_list(&detail.models));
    } else {
        let _ = writeln!(out, "      status      {}", cap.detail);
    }
    let mut flags = vec![detail.locality.clone()];
    flags.push(if detail.auth_configured {
        "auth configured".into()
    } else {
        "no auth".into()
    });
    if detail.selected {
        flags.push("default provider".into());
    }
    let _ = writeln!(out, "      locality    {}", flags.join(" · "));
}

fn readiness_style(readiness: NodeReadiness) -> String {
    match readiness {
        NodeReadiness::Ready => style(readiness.label()).green().bold().to_string(),
        NodeReadiness::Degraded => style(readiness.label()).yellow().bold().to_string(),
        NodeReadiness::Blocked => style(readiness.label()).red().bold().to_string(),
    }
}

/// `rain rig status`.
pub fn status(status: &RigStatus) -> String {
    let mut out = String::new();
    let _ = writeln!(
        out,
        "{} // NODE {}",
        style("R.A.I.N. RIG").bold(),
        status.identity.node
    );

    heading(&mut out, "SYSTEM");
    let ready_state = match status.readiness {
        NodeReadiness::Ready => CapabilityState::Running,
        NodeReadiness::Degraded => CapabilityState::Degraded,
        NodeReadiness::Blocked => CapabilityState::Unavailable,
    };
    let _ = writeln!(
        out,
        "  {} {}",
        glyph(ready_state),
        status.readiness.label().to_ascii_lowercase()
    );
    let mode = status
        .runtime
        .profile
        .map_or_else(|| "default (no profile)".to_string(), |p| p.to_string());
    let _ = writeln!(out, "  mode         {mode}");
    let _ = writeln!(
        out,
        "  privacy      {} ({})",
        status.privacy.mode.label(),
        match status.privacy.source {
            crate::config::RigPrivacySource::Explicit => "set in [rig]",
            crate::config::RigPrivacySource::Profile => "from profile",
            crate::config::RigPrivacySource::Default => "default",
        }
    );
    let _ = writeln!(out, "  runtime      rain {}", status.runtime.version);

    heading(&mut out, "INTELLIGENCE");
    for cap in status.in_category(CapabilityCategory::Inference) {
        inference_block(&mut out, cap);
    }

    heading(&mut out, "R.A.I.N.");
    for cap in status.in_category(CapabilityCategory::Research) {
        line(&mut out, cap);
    }

    heading(&mut out, "DECISION");
    for cap in status.in_category(CapabilityCategory::Decision) {
        line(&mut out, cap);
    }

    heading(&mut out, "TRANSPORTS");
    for cap in status.in_category(CapabilityCategory::Transport) {
        line(&mut out, cap);
    }

    heading(&mut out, "HARDWARE");
    for cap in status
        .in_category(CapabilityCategory::Hardware)
        .chain(status.in_category(CapabilityCategory::Radio))
    {
        line(&mut out, cap);
    }

    heading(&mut out, "STORAGE");
    for cap in status.in_category(CapabilityCategory::Storage) {
        line(&mut out, cap);
    }

    heading(&mut out, "NETWORK");
    for cap in status.in_category(CapabilityCategory::Network) {
        line(&mut out, cap);
    }
    for listener in &status.network.listeners {
        let text = format!(
            "  listener     {} {}:{} ({})",
            listener.component,
            listener.host,
            listener.port,
            listener.exposure.label()
        );
        if listener.exposure.is_loopback() {
            let _ = writeln!(out, "{text}");
        } else {
            let _ = writeln!(
                out,
                "{}",
                style(format!("{text}  ⚠ EXTERNAL BIND")).red().bold()
            );
        }
    }
    let _ = writeln!(
        out,
        "  external services    {}",
        status.network.external_services
    );
    for service in &status.privacy.external_services {
        let _ = writeln!(out, "    - {} ({})", service.name, service.kind);
    }

    if !status.notices.is_empty() || !status.reasons.is_empty() {
        heading(&mut out, "ATTENTION");
        for notice in &status.notices {
            let _ = writeln!(out, "  {} {notice}", style("!").yellow().bold());
        }
        for reason in &status.reasons {
            let _ = writeln!(out, "  {} {reason}", style("!").red().bold());
        }
    }

    let _ = writeln!(out, "\nNODE STATUS: {}", readiness_style(status.readiness));
    out
}

/// `rain rig models`.
pub fn models(statuses: &[CapabilityStatus], default_model: Option<&str>) -> String {
    let mut out = String::new();
    let _ = writeln!(out, "{}", style("R.A.I.N. RIG // MODELS").bold());
    for cap in statuses {
        let Some(detail) = cap.inference.as_ref() else {
            continue;
        };
        let endpoint = detail.endpoint.as_deref().unwrap_or("(no endpoint)");
        let selected = if detail.selected {
            " · default provider"
        } else {
            ""
        };
        let _ = writeln!(
            out,
            "\n{} {}  {}  {}{}",
            glyph(cap.state),
            style(&cap.name).bold(),
            endpoint,
            cap.state.as_str(),
            selected
        );
        if cap.state == CapabilityState::Running && !detail.models.is_empty() {
            for model in &detail.models {
                let marker = if detail.selected && Some(model.as_str()) == default_model {
                    " ← default_model"
                } else {
                    ""
                };
                let _ = writeln!(out, "    {model}{marker}");
            }
            for model in &detail.hosted_models {
                let _ = writeln!(out, "    {model} (hosted via Ollama cloud)");
            }
        } else {
            let _ = writeln!(out, "    {}", cap.detail);
        }
    }
    out
}

/// `rain rig capabilities`.
pub fn capabilities(statuses: &[CapabilityStatus]) -> String {
    let mut out = String::new();
    let _ = writeln!(out, "{}", style("R.A.I.N. RIG // CAPABILITIES").bold());
    for category in CapabilityCategory::ALL {
        let members: Vec<&CapabilityStatus> = statuses
            .iter()
            .filter(|cap| cap.category == category)
            .collect();
        if members.is_empty() {
            continue;
        }
        heading(&mut out, &category.as_str().to_ascii_uppercase());
        for cap in members {
            let summary = super::capability::descriptor(&cap.id)
                .map_or(cap.detail.as_str(), |descriptor| descriptor.summary);
            let mut flags = Vec::new();
            if cap.optional {
                flags.push("optional");
            }
            if cap.experimental {
                flags.push("experimental");
            }
            let flags = if flags.is_empty() {
                String::new()
            } else {
                format!(" [{}]", flags.join(", "))
            };
            let _ = writeln!(
                out,
                "  {} {:<26} {:<12} {summary}{flags}",
                glyph(cap.state),
                cap.id,
                cap.state.as_str()
            );
        }
    }
    out
}

/// `rain rig peers`.
pub fn peers(
    status: &RigStatus,
    identity_json: &str,
    allowed_peers: usize,
    seen: &PeersSeen,
) -> String {
    let mut out = String::new();
    let _ = writeln!(
        out,
        "{} // NODE {}",
        style("R.A.I.N. RIG // PEERS").bold(),
        status.identity.node
    );
    heading(&mut out, "SHAREABLE IDENTITY");
    let _ = writeln!(out, "  {identity_json}");
    heading(&mut out, "PEER TRANSPORTS");
    for id in ["reticulum", "lxmf", "skybridge", "local-network"] {
        if let Some(cap) = status.get(id) {
            line(&mut out, cap);
        }
    }
    let _ = writeln!(
        out,
        "  node_transport allowlist    {allowed_peers} peer(s) configured"
    );
    heading(&mut out, "PEERS SEEN");
    match seen {
        PeersSeen::BridgeDisabled => {
            let _ = writeln!(
                out,
                "  none · the Reticulum/LXMF bridge is disabled (set [rig.bridge] enabled = true)\n  \
                 (Skybridge decodes frames on demand with `rain rig radio decode`)"
            );
        }
        PeersSeen::Unreachable(error) => {
            let _ = writeln!(out, "  unknown · bridge not reachable: {error}");
        }
        PeersSeen::Seen(peers) if peers.is_empty() => {
            let _ = writeln!(
                out,
                "  none yet · LXMF peers appear here after they announce on the Reticulum network"
            );
        }
        PeersSeen::Seen(peers) => {
            for peer in peers {
                let when = chrono::DateTime::from_timestamp(peer.last_seen, 0).map_or_else(
                    || "unknown".to_string(),
                    |t| t.format("%Y-%m-%d %H:%M UTC").to_string(),
                );
                let _ = writeln!(
                    out,
                    "  {}  {:<32}  last announce {when}",
                    peer.hash,
                    peer.name.as_deref().unwrap_or("-")
                );
            }
        }
    }
    out
}

/// Peers observed through the bridge, for `rain rig peers`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PeersSeen {
    BridgeDisabled,
    Unreachable(String),
    Seen(Vec<crate::rig::transport::bridge::BridgePeer>),
}

/// `rain rig doctor`.
pub fn doctor(report: &DoctorReport) -> String {
    let mut out = String::new();
    let _ = writeln!(
        out,
        "{} // NODE {}",
        style("R.A.I.N. RIG DOCTOR").bold(),
        report.node
    );
    let mut area = "";
    for check in &report.checks {
        if check.area != area {
            area = check.area;
            heading(&mut out, &area.to_ascii_uppercase());
        }
        let label = match check.result {
            CheckResult::Pass => style(check.result.label()).green().bold(),
            CheckResult::Warn => style(check.result.label()).yellow().bold(),
            CheckResult::Fail => style(check.result.label()).red().bold(),
            CheckResult::Skip => style(check.result.label()).dim(),
        };
        let _ = writeln!(out, "  {label}  {:<26} {}", check.name, check.message);
        if let Some(hint) = &check.hint {
            let _ = writeln!(out, "        {} {hint}", style("↳").dim());
        }
    }
    let summary = report.summary;
    let _ = writeln!(
        out,
        "\nSUMMARY  {} pass · {} warn · {} fail · {} skip",
        summary.pass, summary.warn, summary.fail, summary.skip
    );
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::rig::test_support::context;

    #[tokio::test]
    async fn status_view_has_every_section_and_node_status() {
        let status = crate::rig::status::collect(&context()).await;
        let text = console::strip_ansi_codes(&super::status(&status)).to_string();
        for section in [
            "R.A.I.N. RIG // NODE rain-local",
            "SYSTEM",
            "INTELLIGENCE",
            "llama.cpp",
            "Ollama",
            "LM Studio",
            "R.A.I.N.",
            "James",
            "DECISION",
            "Deterministic validation",
            "TRANSPORTS",
            "Reticulum",
            "Skybridge [experimental]",
            "NETWORK",
            "external services",
            "NODE STATUS:",
        ] {
            assert!(text.contains(section), "missing {section:?} in\n{text}");
        }
    }

    #[tokio::test]
    async fn doctor_view_lists_results_and_summary() {
        let report = crate::rig::doctor::run(&context()).await;
        let text = console::strip_ansi_codes(&doctor(&report)).to_string();
        assert!(text.contains("SUMMARY"));
        assert!(text.contains("PASS"));
        assert!(text.contains("RF transmit"));
    }
}
