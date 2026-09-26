//! Discovery for optional transports. Read-only: nothing is started,
//! configured, or installed, and R.A.I.N. behaves normally when none exist.

use super::bridge::{BridgeClient, BridgeStatus};
use crate::rig::capability::{CapabilityState, CapabilityStatus, TransportDetail};
use crate::rig::context::RigContext;
use std::path::PathBuf;

/// Reticulum's default shared-instance TCP port.
pub const RETICULUM_SHARED_INSTANCE_PORT: u16 = 37428;

/// Reticulum MTU-bounded payload budget used for the adapter description.
pub const RETICULUM_MAX_PAYLOAD: usize = 383;

/// LXMF payload limit through the bridge (matches the restricted inbox).
pub const LXMF_MAX_PAYLOAD: usize = crate::rig::inbox::MAX_INBOUND_BYTES;

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

pub(crate) fn reticulum_detail() -> TransportDetail {
    TransportDetail {
        bidirectional: true,
        max_payload_bytes: RETICULUM_MAX_PAYLOAD,
        send_supported: false,
        rf_transmit: false,
    }
}

/// LXMF adapter properties: it can send only when the bridge is enabled.
pub(crate) fn lxmf_detail(bridge_enabled: bool) -> TransportDetail {
    if bridge_enabled {
        TransportDetail {
            bidirectional: true,
            max_payload_bytes: LXMF_MAX_PAYLOAD,
            send_supported: true,
            rf_transmit: false,
        }
    } else {
        reticulum_detail()
    }
}

/// What a bridge probe observed.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum BridgeObservation {
    /// `[rig.bridge]` is absent or `enabled = false`; nothing was contacted.
    Disabled,
    /// Enabled, but connecting or authenticating failed.
    Unreachable { endpoint: String, error: String },
    /// Authenticated session and status reply.
    Connected {
        endpoint: String,
        status: BridgeStatus,
    },
}

/// Contact the bridge only when it is enabled.
pub async fn observe_bridge(bridge: Option<&BridgeClient>) -> BridgeObservation {
    let Some(bridge) = bridge else {
        return BridgeObservation::Disabled;
    };
    let endpoint = bridge.endpoint();
    let result = match bridge.connect().await {
        Ok(mut session) => session.status().await,
        Err(error) => Err(error),
    };
    match result {
        Ok(status) => BridgeObservation::Connected { endpoint, status },
        Err(error) => BridgeObservation::Unreachable {
            endpoint,
            error: error.to_string(),
        },
    }
}

/// Bridge client for the configured `[rig.bridge]`, if enabled.
pub fn configured_bridge(ctx: &RigContext) -> Option<BridgeClient> {
    ctx.config
        .rig
        .enabled_bridge()
        .map(|bridge| BridgeClient::new(bridge.port, &ctx.state_dir()))
}

/// Map observed Reticulum facts to a status (pure; unit-tested).
pub fn reticulum_status(facts: InstallFacts, shared_instance: Option<&str>) -> CapabilityStatus {
    let status = match (shared_instance, facts) {
        (Some(via), _) => CapabilityStatus::new(
            "reticulum",
            CapabilityState::Running,
            format!(
                "shared instance reachable ({via}) · raw packets are not bridged; messaging uses lxmf"
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
            "lxmd config found · not probed (enable [rig.bridge] for R.A.I.N. messaging)",
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

/// LXMF status including the R.A.I.N. bridge (pure; unit-tested).
///
/// `running` requires an authenticated bridge session; install facts alone
/// never produce it.
pub fn lxmf_status_with_bridge(
    facts: InstallFacts,
    bridge: &BridgeObservation,
) -> CapabilityStatus {
    match bridge {
        BridgeObservation::Disabled => lxmf_status(facts),
        BridgeObservation::Unreachable { endpoint, error } => CapabilityStatus::new(
            "lxmf",
            CapabilityState::Configured,
            format!("R.A.I.N. bridge enabled · not reachable on {endpoint} ({error}); start it with `rain rig up`"),
        )
        .with_transport(lxmf_detail(true)),
        BridgeObservation::Connected { endpoint, status } => {
            let address = status.lxmf_address.as_deref().unwrap_or("unknown");
            CapabilityStatus::new(
                "lxmf",
                CapabilityState::Running,
                format!(
                    "R.A.I.N. bridge on {endpoint} · address {address} · {} peer(s) seen · {} message(s) queued",
                    status.peers, status.queued_inbound
                ),
            )
            .with_transport(lxmf_detail(true))
        }
    }
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
    let bridge = observe_bridge(configured_bridge(ctx).as_ref()).await;
    vec![
        loopback_status(),
        reticulum_status(reticulum_facts, shared),
        lxmf_status_with_bridge(lxmf_facts, &bridge),
        crate::rig::skybridge::skybridge_status(),
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
    fn lxmf_runs_only_with_an_authenticated_bridge() {
        let facts = InstallFacts::default();
        let disabled = lxmf_status_with_bridge(facts, &BridgeObservation::Disabled);
        assert_eq!(disabled.state, CapabilityState::Unavailable);
        assert!(!disabled.transport.unwrap().send_supported);

        let unreachable = lxmf_status_with_bridge(
            facts,
            &BridgeObservation::Unreachable {
                endpoint: "127.0.0.1:42627".into(),
                error: "refused".into(),
            },
        );
        assert_eq!(unreachable.state, CapabilityState::Configured);
        assert!(unreachable.detail.contains("rain rig up"));

        let connected = lxmf_status_with_bridge(
            facts,
            &BridgeObservation::Connected {
                endpoint: "127.0.0.1:42627".into(),
                status: BridgeStatus {
                    backend: "rns".into(),
                    lxmf_address: Some("0123456789abcdef0123456789abcdef".into()),
                    peers: 2,
                    ..BridgeStatus::default()
                },
            },
        );
        assert_eq!(connected.state, CapabilityState::Running);
        let detail = connected.transport.unwrap();
        assert!(detail.send_supported && !detail.rf_transmit);
        assert_eq!(detail.max_payload_bytes, LXMF_MAX_PAYLOAD);
    }

    #[test]
    fn loopback_transport_has_no_rf_and_no_listener() {
        let status = loopback_status();
        assert_eq!(status.state, CapabilityState::Available);
        assert!(!status.transport.unwrap().rf_transmit);
    }
}
