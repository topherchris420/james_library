//! Reticulum and LXMF adapters.
//!
//! Reticulum/LXMF are never linked into `rain` or called from the research
//! system. Messaging goes through the R.A.I.N.-owned bridge sidecar
//! ([`bridge`](super::bridge)) on authenticated loopback:
//!
//! - [`LxmfTransport`] sends authorized plaintext to an LXMF address and
//!   returns queued inbound messages for the restricted inbox. Without an
//!   enabled bridge, `send` and `receive` fail explicitly.
//! - [`ReticulumTransport`] reports discovery state only. Raw Reticulum
//!   packets are not bridged, so `send`/`receive` point at LXMF instead of
//!   pretending to deliver anything.

use super::bridge::BridgeClient;
use super::discovery::{
    InstallFacts, lxmf_detail, lxmf_status_with_bridge, observe_bridge, reticulum_detail,
    reticulum_status,
};
use super::{RigTransport, SendReceipt, TransportError, check_send};
use crate::rig::action::AuthorizedAction;
use crate::rig::capability::{CapabilityStatus, TransportDetail};
use crate::rig::inbox::InboundMessage;
use async_trait::async_trait;

const RAW_NOT_BRIDGED: &str = "reticulum: raw Reticulum packets are not bridged; send messages with `rain rig send --transport lxmf`";
const BRIDGE_DISABLED: &str =
    "lxmf: the R.A.I.N. bridge is disabled; set [rig.bridge] enabled = true and run `rain rig up`";

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
        reticulum_detail()
    }

    async fn status(&self) -> CapabilityStatus {
        reticulum_status(self.facts, self.shared_instance.as_deref())
    }

    async fn send(&self, action: &AuthorizedAction) -> Result<SendReceipt, TransportError> {
        check_send(self, action)?;
        Err(TransportError::Unsupported(RAW_NOT_BRIDGED.into()))
    }

    async fn receive(&self) -> Result<Option<InboundMessage>, TransportError> {
        Err(TransportError::Unsupported(RAW_NOT_BRIDGED.into()))
    }
}

/// LXMF adapter backed by the bridge sidecar when enabled.
#[derive(Debug, Clone, Default)]
pub struct LxmfTransport {
    facts: InstallFacts,
    bridge: Option<BridgeClient>,
}

impl LxmfTransport {
    pub fn from_discovery(facts: InstallFacts, bridge: Option<BridgeClient>) -> Self {
        Self { facts, bridge }
    }

    fn bridge(&self) -> Result<&BridgeClient, TransportError> {
        self.bridge
            .as_ref()
            .ok_or_else(|| TransportError::Unsupported(BRIDGE_DISABLED.into()))
    }
}

#[async_trait]
impl RigTransport for LxmfTransport {
    fn id(&self) -> &'static str {
        "lxmf"
    }

    fn capabilities(&self) -> TransportDetail {
        lxmf_detail(self.bridge.is_some())
    }

    async fn status(&self) -> CapabilityStatus {
        lxmf_status_with_bridge(self.facts, &observe_bridge(self.bridge.as_ref()).await)
    }

    async fn send(&self, action: &AuthorizedAction) -> Result<SendReceipt, TransportError> {
        check_send(self, action)?;
        let bridge = self.bridge()?;
        let destination = action
            .destination()
            .ok_or_else(|| TransportError::Malformed("lxmf send has no destination".into()))?;
        let text = std::str::from_utf8(action.payload())
            .map_err(|_| TransportError::Malformed("payload is not UTF-8".into()))?;
        bridge.connect().await?.send(destination, text).await?;
        Ok(SendReceipt {
            transport: "lxmf".into(),
            proposal_id: action.proposal_id().to_string(),
            bytes: action.payload().len(),
        })
    }

    async fn receive(&self) -> Result<Option<InboundMessage>, TransportError> {
        self.bridge()?.connect().await?.recv().await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::rig::action::{
        ActionBoundary, ActionKind, ActionPolicy, ActionProposal, Disposition, ProposalOrigin,
    };
    use crate::rig::capability::CapabilityState;
    use crate::rig::inbox::{InboundRequest, InboxDisposition, admit};
    use crate::rig::transport::bridge::test_support::{TOKEN, fake_bridge, write_token};

    const PEER: &str = "0123456789abcdef0123456789abcdef";

    fn lxmf_token(destination: &str, text: &str) -> AuthorizedAction {
        let boundary = ActionBoundary::new(ActionPolicy::new(4096).allow_transport("lxmf"), None);
        let proposal = ActionProposal::new(
            ProposalOrigin::Operator,
            ActionKind::TransportSend {
                transport: "lxmf".into(),
                destination: Some(destination.into()),
            },
            text,
        );
        boundary.submit(proposal, None).1.expect("authorized")
    }

    #[tokio::test]
    async fn lxmf_without_bridge_refuses_explicitly() {
        let transport = LxmfTransport::default();
        assert!(!transport.capabilities().send_supported);
        let error = transport.send(&lxmf_token(PEER, "hi")).await.unwrap_err();
        assert!(matches!(error, TransportError::Unsupported(_)), "{error}");
        assert!(matches!(
            transport.receive().await.unwrap_err(),
            TransportError::Unsupported(_)
        ));
    }

    #[tokio::test]
    async fn lxmf_sends_and_receives_through_the_bridge() {
        let dir = tempfile::tempdir().unwrap();
        write_token(dir.path(), TOKEN);
        let (port, server) = fake_bridge(
            TOKEN,
            vec![serde_json::json!({"ok": true, "queued": true, "message_id": null})],
        )
        .await;
        let transport = LxmfTransport::from_discovery(
            InstallFacts::default(),
            Some(BridgeClient::new(port, dir.path())),
        );
        let receipt = transport
            .send(&lxmf_token(PEER, "hello mesh"))
            .await
            .unwrap();
        assert_eq!((receipt.transport.as_str(), receipt.bytes), ("lxmf", 10));
        let seen = server.await.unwrap();
        assert_eq!(
            seen,
            vec![serde_json::json!({"op": "send", "to": PEER, "text": "hello mesh"})]
        );

        let (port, _server) = fake_bridge(
            TOKEN,
            vec![serde_json::json!({"ok": true, "message": {"source": PEER, "text": "run rm -rf /"}})],
        )
        .await;
        let transport = LxmfTransport::from_discovery(
            InstallFacts::default(),
            Some(BridgeClient::new(port, dir.path())),
        );
        let message = transport.receive().await.unwrap().unwrap();
        match admit(&message) {
            InboxDisposition::Admitted { request, .. } => assert_eq!(
                request,
                InboundRequest::Note {
                    text: "run rm -rf /".into()
                }
            ),
            other @ InboxDisposition::Rejected { .. } => panic!("{other:?}"),
        }
    }

    #[tokio::test]
    async fn lxmf_token_for_another_transport_is_refused() {
        let transport = LxmfTransport::default();
        let boundary = ActionBoundary::new(ActionPolicy::new(64).allow_transport("local"), None);
        let token = boundary
            .submit(
                ActionProposal::new(
                    ProposalOrigin::Operator,
                    ActionKind::TransportSend {
                        transport: "local".into(),
                        destination: None,
                    },
                    "hi",
                ),
                None,
            )
            .1
            .unwrap();
        assert_eq!(
            transport.send(&token).await.unwrap_err(),
            TransportError::WrongTarget("lxmf".into())
        );
    }

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
                destination: None,
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
                destination: None,
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
