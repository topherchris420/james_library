//! Discovery for optional transports. Read-only: nothing is started,
//! configured, or installed, and R.A.I.N. behaves normally when none exist.

use crate::rig::capability::{CapabilityState, CapabilityStatus, TransportDetail};
use crate::rig::context::RigContext;
use std::path::PathBuf;

/// Reticulum's default shared-instance TCP port.
pub const RETICULUM_SHARED_INSTANCE_PORT: u16 = 37428;

/// Reticulum MTU-bounded payload budget used for the adapter description.
pub const RETICULUM_MAX_PAYLOAD: usize = 383;

fn home_dir() -> Option<PathBuf> {
    directories::UserDirs::new().map(|dirs| dirs.home_dir().to_path_buf())
}

/// Reticulum configuration files, in RNS search order.
fn reticulum_config_candidates() -> Vec<PathBuf> {
    let mut candidates = vec![PathBuf::from("/etc/reticulum/config")];
    if let Some(home) = home_dir() {
        candidates.push(home.join(".config/reticulum/config"));
        candidates.push(home.join(".reticulum/config"));
    }
    candidates
}

fn lxmd_config_candidates() -> Vec<PathBuf> {
    let mut candidates = vec![PathBuf::from("/etc/lxmd/config")];
    if let Some(home) = home_dir() {
        candidates.push(home.join(".config/lxmd/config"));
        candidates.push(home.join(".lxmd/config"));
    }
    candidates
}

/// Observable facts about an optional installation.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct InstallFacts {
    pub binary_on_path: bool,
    pub config_present: bool,
}

impl InstallFacts {
    fn detect(binary: &str, configs: &[PathBuf]) -> Self {
        Self {
            binary_on_path: which::which(binary).is_ok(),
            config_present: configs.iter().any(|path| path.is_file()),
        }
    }
}

/// Whether a Reticulum shared instance accepts local connections.
///
/// Checks the default TCP shared-instance port and, on Linux, the default
/// abstract Unix socket. Connecting is harmless: rnsd treats it as a local
/// client that immediately disconnects. No data is sent.
async fn reticulum_shared_instance(ctx: &RigContext) -> Option<&'static str> {
    if ctx
        .probe
        .tcp_open("127.0.0.1", RETICULUM_SHARED_INSTANCE_PORT)
        .await
    {
        return Some("tcp 127.0.0.1:37428");
    }
    #[cfg(target_os = "linux")]
    {
        use std::os::linux::net::SocketAddrExt;
        let connected = tokio::task::spawn_blocking(|| {
            std::os::unix::net::SocketAddr::from_abstract_name(b"rns/default")
                .and_then(|address| std::os::unix::net::UnixStream::connect_addr(&address))
                .is_ok()
        })
        .await
        .unwrap_or(false);
        if connected {
            return Some("unix @rns/default");
        }
    }
    None
}

fn reticulum_detail() -> TransportDetail {
    TransportDetail {
        bidirectional: true,
        max_payload_bytes: RETICULUM_MAX_PAYLOAD,
        send_supported: false,
        rf_transmit: false,
    }
}

/// Map observed Reticulum facts to a status (pure; unit-tested).
pub fn reticulum_status(facts: InstallFacts, shared_instance: Option<&str>) -> CapabilityStatus {
    let status = match (shared_instance, facts) {
        (Some(via), _) => CapabilityStatus::new(
            "reticulum",
            CapabilityState::Running,
            format!(
                "shared instance reachable ({via}) · discovery only; no R.A.I.N. bridge in this build"
            ),
        ),
        (
            None,
            InstallFacts {
                config_present: true,
                ..
            },
        ) => CapabilityStatus::new(
            "reticulum",
            CapabilityState::Configured,
            "config found · no shared instance detected (start rnsd)",
        ),
        (
            None,
            InstallFacts {
                binary_on_path: true,
                ..
            },
        ) => CapabilityStatus::new(
            "reticulum",
            CapabilityState::Unavailable,
            "rnsd installed · not configured or running",
        ),
        (None, _) => CapabilityStatus::new(
            "reticulum",
            CapabilityState::Unavailable,
            "not installed (optional)",
        ),
    };
    status.with_transport(reticulum_detail())
}

/// Map observed LXMF facts to a status (pure; unit-tested).
///
/// `lxmd` exposes no local endpoint, so the Rig never reports it running.
pub fn lxmf_status(facts: InstallFacts) -> CapabilityStatus {
    let status = match facts {
        InstallFacts {
            config_present: true,
            ..
        } => CapabilityStatus::new(
            "lxmf",
            CapabilityState::Configured,
            "lxmd config found · running state not probed (lxmd has no local endpoint)",
        ),
        InstallFacts {
            binary_on_path: true,
            ..
        } => CapabilityStatus::new(
            "lxmf",
            CapabilityState::Unavailable,
            "lxmd installed · not configured",
        ),
        _ => CapabilityStatus::new(
            "lxmf",
            CapabilityState::Unavailable,
            "not installed (optional)",
        ),
    };
    status.with_transport(reticulum_detail())
}

/// In-process loopback transport status.
pub fn loopback_status() -> CapabilityStatus {
    CapabilityStatus::new(
        "local",
        CapabilityState::Available,
        "in-process loopback · no network listener",
    )
    .with_transport(TransportDetail {
        bidirectional: true,
        max_payload_bytes: crate::rig::inbox::MAX_INBOUND_BYTES,
        send_supported: true,
        rf_transmit: false,
    })
}

/// Discover all transports.
pub async fn probe_transports(ctx: &RigContext) -> Vec<CapabilityStatus> {
    let reticulum_facts = InstallFacts::detect("rnsd", &reticulum_config_candidates());
    let lxmf_facts = InstallFacts::detect("lxmd", &lxmd_config_candidates());
    let shared = reticulum_shared_instance(ctx).await;
    vec![
        loopback_status(),
        reticulum_status(reticulum_facts, shared),
        lxmf_status(lxmf_facts),
    ]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reticulum_is_never_running_without_a_positive_probe() {
        let installed = InstallFacts {
            binary_on_path: true,
            config_present: true,
        };
        assert_eq!(
            reticulum_status(installed, None).state,
            CapabilityState::Configured
        );
        let binary_only = InstallFacts {
            binary_on_path: true,
            config_present: false,
        };
        assert_eq!(
            reticulum_status(binary_only, None).state,
            CapabilityState::Unavailable
        );
        assert_eq!(
            reticulum_status(InstallFacts::default(), None).state,
            CapabilityState::Unavailable
        );
        let running = reticulum_status(InstallFacts::default(), Some("tcp 127.0.0.1:37428"));
        assert_eq!(running.state, CapabilityState::Running);
        assert!(!running.transport.unwrap().send_supported);
    }

    #[test]
    fn lxmf_never_claims_running() {
        for facts in [
            InstallFacts::default(),
            InstallFacts {
                binary_on_path: true,
                config_present: false,
            },
            InstallFacts {
                binary_on_path: true,
                config_present: true,
            },
        ] {
            assert_ne!(lxmf_status(facts).state, CapabilityState::Running);
        }
    }

    #[test]
    fn loopback_transport_has_no_rf_and_no_listener() {
        let status = loopback_status();
        assert_eq!(status.state, CapabilityState::Available);
        assert!(!status.transport.unwrap().rf_transmit);
    }
}
