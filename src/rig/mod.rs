//! R.A.I.N. Rig — optional appliance layer that runs R.A.I.N. Lab as a
//! self-contained local research node.
//!
//! The Rig is additive and opt-in. It observes, reports, and coordinates;
//! it does not replace `python rain_lab.py` or change the research meeting.
//!
//! ```text
//! R.A.I.N. Lab (James · Jasmine · Luca · Elena)
//!         │
//! decision / authorization boundary  ── action (policy → validation → human)
//!         │
//! Rig capability bus ── capability registry + status/doctor
//!    │            │                 │
//! inference     research        transports / hardware
//! (providers)   (library)       (loopback · Reticulum · LXMF · Skybridge)
//! ```
//!
//! Safety properties:
//! - Discovery never contacts remote services, never starts third-party
//!   servers, and degrades gracefully when optional pieces are missing.
//! - Transports can only send with an [`action::AuthorizedAction`], which
//!   only the action boundary mints; inbound data can only become inert
//!   [`inbox::InboundRequest`]s.
//! - Skybridge is software-only; RF transmit is disabled in this build.

pub mod action;
pub mod capability;
pub mod cli;
pub mod context;
pub mod doctor;
pub mod identity;
pub mod inbox;
pub mod inference;
pub mod probe;
pub mod render;
pub mod research;
pub mod setup;
pub mod skybridge;
pub mod status;
pub mod system;
pub mod transport;
pub mod up;

pub use cli::handle_command;

#[cfg(test)]
pub(crate) mod test_support {
    //! Deterministic fixtures: no real servers, no ambient environment.

    use super::context::{ProbeEndpoints, RigContext, RigEnv};
    use super::probe::ProbeClient;
    use crate::config::Config;
    use std::path::Path;

    pub fn unused_local_port() -> u16 {
        std::net::TcpListener::bind("127.0.0.1:0")
            .and_then(|listener| listener.local_addr())
            .map(|address| address.port())
            .expect("bind an ephemeral loopback port")
    }

    /// A loopback URL nothing listens on.
    pub fn unreachable_url(suffix: &str) -> String {
        format!("http://127.0.0.1:{}{suffix}", unused_local_port())
    }

    /// Context with every probe target unreachable and a neutral environment.
    pub fn context() -> RigContext {
        context_with_endpoints(None, None, None)
    }

    pub fn context_with_endpoints(
        llamacpp: Option<String>,
        ollama: Option<String>,
        lmstudio: Option<String>,
    ) -> RigContext {
        let mut config = Config::default();
        config.gateway.port = unused_local_port();
        config.workspace_dir = std::env::temp_dir();
        RigContext {
            config,
            env: RigEnv::from_pairs([("RAIN_LLM_BASE_URL", unreachable_url("/v1"))]),
            library_root: None,
            endpoints: ProbeEndpoints {
                llamacpp: llamacpp.unwrap_or_else(|| unreachable_url("/v1")),
                ollama: ollama.unwrap_or_else(|| unreachable_url("")),
                lmstudio: lmstudio.unwrap_or_else(|| unreachable_url("/v1")),
            },
            probe: ProbeClient::new(),
        }
    }

    /// Minimal research library: launcher, four personas, one paper.
    pub fn write_library(root: &Path) {
        std::fs::write(root.join("rain_lab.py"), "").unwrap();
        for (_, file) in super::research::RESEARCH_AGENTS {
            std::fs::write(root.join(file), "# soul").unwrap();
        }
        std::fs::create_dir_all(root.join("papers")).unwrap();
        std::fs::write(root.join("papers/paper.md"), "# paper").unwrap();
    }
}
