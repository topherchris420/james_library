//! RF transmit backend interface — disabled in this build.
//!
//! A future hardware backend (transceiver, SDR) would implement
//! [`RfTransmitBackend`]. Two independent guards keep transmission
//! impossible here:
//!
//! 1. The action boundary rejects every `RadioTransmit` proposal, so no
//!    [`AuthorizedAction`] for radio transmit can exist.
//! 2. The only backend compiled in, [`DisabledRfBackend`], refuses every
//!    call regardless of the token presented.
//!
//! No code in this build keys a transmitter, selects a frequency, sets RF
//! power, or opens an SDR device.

use crate::rig::action::{ActionKind, AuthorizedAction};

/// RF transmit failure.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum RadioError {
    #[error("RF transmit is disabled: no radio/SDR transmit backend exists in this build")]
    TransmitDisabled,
    #[error("authorization does not cover radio transmit")]
    NotRadioAuthorization,
}

/// Interface a hardware transmit backend must implement.
pub trait RfTransmitBackend: Send + Sync {
    fn name(&self) -> &'static str;

    /// Whether the backend can emit RF at all.
    fn can_transmit(&self) -> bool;

    /// Transmit baseband samples. Requires a radio-transmit authorization.
    fn transmit(&self, samples: &[f32], authorization: &AuthorizedAction)
    -> Result<(), RadioError>;
}

/// The only backend in this build: refuses everything.
#[derive(Debug, Clone, Copy, Default)]
pub struct DisabledRfBackend;

impl RfTransmitBackend for DisabledRfBackend {
    fn name(&self) -> &'static str {
        "none"
    }

    fn can_transmit(&self) -> bool {
        false
    }

    fn transmit(
        &self,
        _samples: &[f32],
        authorization: &AuthorizedAction,
    ) -> Result<(), RadioError> {
        if !matches!(authorization.kind(), ActionKind::RadioTransmit) {
            return Err(RadioError::NotRadioAuthorization);
        }
        Err(RadioError::TransmitDisabled)
    }
}

/// The RF backend in use. Always [`DisabledRfBackend`] in this build.
pub fn active_backend() -> &'static dyn RfTransmitBackend {
    &DisabledRfBackend
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::rig::action::{
        ActionBoundary, ActionPolicy, ActionProposal, Disposition, HumanApproval, ProposalOrigin,
    };

    #[test]
    fn no_rf_backend_is_active_by_default() {
        let backend = active_backend();
        assert_eq!(backend.name(), "none");
        assert!(!backend.can_transmit());
    }

    #[test]
    fn radio_transmit_cannot_be_authorized_even_by_an_operator() {
        let boundary =
            ActionBoundary::new(ActionPolicy::new(256).allow_transport("skybridge"), None);
        let proposal =
            ActionProposal::new(ProposalOrigin::Operator, ActionKind::RadioTransmit, "CQ");
        let approval = HumanApproval::confirmed_by_operator(&proposal.id);
        let (record, token) = boundary.submit(proposal, Some(&approval));
        assert_eq!(record.disposition, Disposition::Rejected);
        assert!(token.is_none());
    }

    #[test]
    fn disabled_backend_refuses_any_token() {
        let boundary =
            ActionBoundary::new(ActionPolicy::new(256).allow_transport("skybridge"), None);
        let proposal = ActionProposal::new(
            ProposalOrigin::Operator,
            ActionKind::TransportSend {
                transport: "skybridge".into(),
                destination: None,
            },
            "hello",
        );
        let token = boundary.submit(proposal, None).1.unwrap();
        assert_eq!(
            active_backend().transmit(&[0.0; 8], &token),
            Err(RadioError::NotRadioAuthorization)
        );
    }
}
