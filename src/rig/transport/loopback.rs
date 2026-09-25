//! In-process loopback transport: a bounded queue inside one R.A.I.N.
//! process. No sockets, no listeners. Used to exercise the full
//! propose → authorize → send → receive → admit pipeline locally.

use super::{RigTransport, SendReceipt, TransportError, check_send};
use crate::rig::action::AuthorizedAction;
use crate::rig::capability::{CapabilityStatus, TransportDetail};
use crate::rig::inbox::InboundMessage;
use async_trait::async_trait;
use std::collections::VecDeque;
use std::sync::Mutex;

const QUEUE_CAPACITY: usize = 64;

#[derive(Debug, Default)]
pub struct LoopbackTransport {
    queue: Mutex<VecDeque<InboundMessage>>,
}

impl LoopbackTransport {
    pub fn new() -> Self {
        Self::default()
    }
}

#[async_trait]
impl RigTransport for LoopbackTransport {
    fn id(&self) -> &'static str {
        "local"
    }

    fn capabilities(&self) -> TransportDetail {
        super::discovery::loopback_status()
            .transport
            .unwrap_or_default()
    }

    async fn status(&self) -> CapabilityStatus {
        super::discovery::loopback_status()
    }

    async fn send(&self, action: &AuthorizedAction) -> Result<SendReceipt, TransportError> {
        check_send(self, action)?;
        let mut queue = self
            .queue
            .lock()
            .map_err(|_| TransportError::Io("loopback queue poisoned".into()))?;
        if queue.len() >= QUEUE_CAPACITY {
            return Err(TransportError::Io("loopback queue full".into()));
        }
        queue.push_back(InboundMessage {
            transport: "local".into(),
            source: "loopback".into(),
            payload: action.payload().to_vec(),
        });
        Ok(SendReceipt {
            transport: "local".into(),
            proposal_id: action.proposal_id().to_string(),
            bytes: action.payload().len(),
        })
    }

    async fn receive(&self) -> Result<Option<InboundMessage>, TransportError> {
        let mut queue = self
            .queue
            .lock()
            .map_err(|_| TransportError::Io("loopback queue poisoned".into()))?;
        Ok(queue.pop_front())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::rig::action::{
        ActionBoundary, ActionKind, ActionPolicy, ActionProposal, ProposalOrigin,
    };
    use crate::rig::inbox::{InboundRequest, InboxDisposition, MAX_INBOUND_BYTES, admit};

    fn boundary() -> ActionBoundary {
        ActionBoundary::new(
            ActionPolicy::new(MAX_INBOUND_BYTES)
                .allow_transport("local")
                .allow_transport("skybridge"),
            None,
        )
    }

    fn authorize(transport: &str, payload: &str) -> AuthorizedAction {
        let proposal = ActionProposal::new(
            ProposalOrigin::Operator,
            ActionKind::TransportSend {
                transport: transport.into(),
            },
            payload,
        );
        boundary().submit(proposal, None).1.expect("authorized")
    }

    #[tokio::test]
    async fn full_pipeline_delivers_inert_request() {
        let transport = LoopbackTransport::new();
        let receipt = transport.send(&authorize("local", "PING")).await.unwrap();
        assert_eq!(receipt.bytes, 4);
        let message = transport.receive().await.unwrap().unwrap();
        match admit(&message) {
            InboxDisposition::Admitted { request, .. } => assert_eq!(request, InboundRequest::Ping),
            other @ InboxDisposition::Rejected { .. } => panic!("{other:?}"),
        }
        assert!(transport.receive().await.unwrap().is_none());
    }

    #[tokio::test]
    async fn token_for_another_transport_is_refused() {
        let transport = LoopbackTransport::new();
        let error = transport
            .send(&authorize("skybridge", "hello"))
            .await
            .unwrap_err();
        assert_eq!(error, TransportError::WrongTarget("local".into()));
        assert!(transport.receive().await.unwrap().is_none());
    }

    #[tokio::test]
    async fn queue_is_bounded() {
        let transport = LoopbackTransport::new();
        for _ in 0..QUEUE_CAPACITY {
            transport.send(&authorize("local", "note")).await.unwrap();
        }
        assert!(transport.send(&authorize("local", "note")).await.is_err());
    }
}
