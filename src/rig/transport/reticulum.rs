//! Reticulum and LXMF adapter boundary.
//!
//! These adapters report real discovery state and define where a future
//! R.A.I.N. ↔ Reticulum bridge plugs in. This build ships no bridge, so
//! `send` and `receive` fail explicitly with [`TransportError::Unsupported`]
//! instead of pretending to deliver anything. Reticulum/LXMF APIs are never
//! called from the research system directly.

use super::discovery::{InstallFacts, RETICULUM_MAX_PAYLOAD, lxmf_status, reticulum_status};
use super::{RigTransport, SendReceipt, TransportError, check_send};
use crate::rig::action::AuthorizedAction;
use crate::rig::capability::{CapabilityStatus, TransportDetail};
use crate::rig::inbox::InboundMessage;
use async_trait::async_trait;

const NO_BRIDGE: &str = "no R.A.I.N. bridge for this transport in this build (discovery only)";

fn detail() -> TransportDetail {
    TransportDetail {
        bidirectional: true,
        max_payload_bytes: RETICULUM_MAX_PAYLOAD,
        send_supported: false,
        rf_transmit: false,
    }
}

/// Reticulum adapter (discovery only).
#[derive(Debug, Clone, Default)]
pub struct ReticulumTransport {
    facts: InstallFacts,
    shared_instance: Option<String>,
}

impl ReticulumTransport {
    pub fn from_discovery(facts: InstallFacts, shared_instance: Option<String>) -> Self {
        Self {
            facts,
            shared_instance,
        }
    }
}

#[async_trait]
impl RigTransport for ReticulumTransport {
    fn id(&self) -> &'static str {
        "reticulum"
    }

    fn capabilities(&self) -> TransportDetail {
        detail()
    }

    async fn status(&self) -> CapabilityStatus {
        reticulum_status(self.facts, self.shared_instance.as_deref())
    }

    async fn send(&self, action: &AuthorizedAction) -> Result<SendReceipt, TransportError> {
        check_send(self, action)?;
        Err(TransportError::Unsupported(format!(
            "reticulum: {NO_BRIDGE}"
        )))
    }

    async fn receive(&self) -> Result<Option<InboundMessage>, TransportError> {
        Err(TransportError::Unsupported(format!(
            "reticulum: {NO_BRIDGE}"
        )))
    }
}

/// LXMF adapter (discovery only).
#[derive(Debug, Clone, Default)]
pub struct LxmfTransport {
    facts: InstallFacts,
}

impl LxmfTransport {
    pub fn from_discovery(facts: InstallFacts) -> Self {
        Self { facts }
    }
}

#[async_trait]
impl RigTransport for LxmfTransport {
    fn id(&self) -> &'static str {
        "lxmf"
    }

    fn capabilities(&self) -> TransportDetail {
        detail()
    }

    async fn status(&self) -> CapabilityStatus {
        lxmf_status(self.facts)
    }

    async fn send(&self, action: &AuthorizedAction) -> Result<SendReceipt, TransportError> {
        check_send(self, action)?;
        Err(TransportError::Unsupported(format!("lxmf: {NO_BRIDGE}")))
    }

    async fn receive(&self) -> Result<Option<InboundMessage>, TransportError> {
        Err(TransportError::Unsupported(format!("lxmf: {NO_BRIDGE}")))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::rig::action::{
        ActionBoundary, ActionKind, ActionPolicy, ActionProposal, Disposition, ProposalOrigin,
    };
    use crate::rig::capability::CapabilityState;

    #[tokio::test]
    async fn missing_reticulum_degrades_gracefully() {
        let transport = ReticulumTransport::default();
        let status = transport.status().await;
        assert_eq!(status.state, CapabilityState::Unavailable);
        assert!(transport.receive().await.is_err());
        let lxmf = LxmfTransport::default();
        assert_eq!(lxmf.status().await.state, CapabilityState::Unavailable);
    }

    #[tokio::test]
    async fn boundary_refuses_sends_to_discovery_only_transports() {
        // Default policy only lists adapters that can send; Reticulum is not one.
        let boundary = ActionBoundary::new(ActionPolicy::new(256).allow_transport("local"), None);
        let proposal = ActionProposal::new(
            ProposalOrigin::Operator,
            ActionKind::TransportSend {
                transport: "reticulum".into(),
            },
            "hello mesh",
        );
        let (record, token) = boundary.submit(proposal, None);
        assert_eq!(record.disposition, Disposition::Rejected);
        assert!(token.is_none());
    }

    #[tokio::test]
    async fn even_an_authorized_send_is_unsupported_not_faked() {
        let boundary =
            ActionBoundary::new(ActionPolicy::new(256).allow_transport("reticulum"), None);
        let proposal = ActionProposal::new(
            ProposalOrigin::Operator,
            ActionKind::TransportSend {
                transport: "reticulum".into(),
            },
            "hello mesh",
        );
        let token = boundary.submit(proposal, None).1.unwrap();
        let error = ReticulumTransport::default()
            .send(&token)
            .await
            .unwrap_err();
        assert!(matches!(error, TransportError::Unsupported(_)));
    }
}
