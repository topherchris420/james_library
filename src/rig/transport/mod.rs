//! Rig transport adapters.
//!
//! A transport moves opaque plaintext payloads between Rig nodes. The
//! contract keeps transports away from the research system and from any
//! execution surface:
//!
//! - [`RigTransport::send`] requires an [`AuthorizedAction`] minted by the
//!   [`action`](crate::rig::action) boundary for *this* transport.
//! - [`RigTransport::receive`] returns raw [`InboundMessage`]s; callers must
//!   pass them through [`inbox::admit`](crate::rig::inbox::admit), which can
//!   only produce inert request kinds.
//! - All transports are optional; R.A.I.N. behaves normally when none exist.

pub mod bridge;
pub mod discovery;
pub mod loopback;
pub mod reticulum;

use super::action::AuthorizedAction;
use super::capability::{CapabilityStatus, TransportDetail};
use super::inbox::InboundMessage;
use async_trait::async_trait;

/// Transport-level failure.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum TransportError {
    /// The adapter exists for discovery but cannot perform this operation.
    #[error("{0}")]
    Unsupported(String),
    /// The authorization token was issued for a different action or transport.
    #[error("authorization does not target transport '{0}'")]
    WrongTarget(String),
    #[error("payload is {bytes} bytes; transport limit is {limit}")]
    PayloadTooLarge { bytes: usize, limit: usize },
    /// Received data or an outbound payload failed codec validation.
    #[error("malformed: {0}")]
    Malformed(String),
    #[error("transport I/O error: {0}")]
    Io(String),
}

/// Confirmation of a completed send.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SendReceipt {
    pub transport: String,
    pub proposal_id: String,
    pub bytes: usize,
}

/// Common transport contract.
#[async_trait]
pub trait RigTransport: Send + Sync {
    /// Capability id (`local`, `reticulum`, `lxmf`, `skybridge`).
    fn id(&self) -> &'static str;

    /// Static properties of this adapter.
    fn capabilities(&self) -> TransportDetail;

    /// Observed state. Must not start or reconfigure anything.
    async fn status(&self) -> CapabilityStatus;

    /// Send the payload of an authorized action.
    async fn send(&self, action: &AuthorizedAction) -> Result<SendReceipt, TransportError>;

    /// Next raw inbound message, if one is waiting.
    async fn receive(&self) -> Result<Option<InboundMessage>, TransportError>;
}

/// Shared pre-send validation for adapters.
pub(crate) fn check_send(
    transport: &dyn RigTransport,
    action: &AuthorizedAction,
) -> Result<(), TransportError> {
    if !action.targets_transport(transport.id()) {
        return Err(TransportError::WrongTarget(transport.id().to_string()));
    }
    let limit = transport.capabilities().max_payload_bytes;
    if action.payload().len() > limit {
        return Err(TransportError::PayloadTooLarge {
            bytes: action.payload().len(),
            limit,
        });
    }
    Ok(())
}
