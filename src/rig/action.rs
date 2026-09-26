//! Rig action boundary.
//!
//! Every outbound Rig action (transport send, baseband render, radio
//! transmit, authoritative config write) is a proposal that must pass:
//!
//! ```text
//! proposal ─▶ policy checks ─▶ deterministic validation ─▶ human authorization
//!          (when required) ─▶ AuthorizedAction ─▶ transport adapter ─▶ execution
//! ```
//!
//! RF transmit (`RadioTransmit`) is rejected unless the binary was built
//! with the off-by-default `rig-rf-transmit` Cargo feature. Even then it must
//! come from a human operator (never a model or host code, not even with an
//! approval), use the configured licensed callsign, keep its 3 kHz USB
//! channel inside [`RF_BAND_PLAN`], stay within the configured power limit,
//! and carry an interactive human confirmation for that exact proposal.
//!
//! Rules (fail closed):
//! - No proposal reaches a transport until every deterministic check passes.
//! - A model's assessment is recorded but never read by a check, so model
//!   judgment cannot override a failed deterministic check. Neither can a
//!   human approval: approvals are only consulted after all checks pass.
//! - Model- or system-originated external actions need a human approval
//!   bound to that exact proposal id.
//! - Every disposition is recorded before a token is released; if the record
//!   cannot be written, the action is rejected.
//! - [`AuthorizedAction`] can only be constructed here, and transport
//!   adapters require one to send.

use anyhow::Context;
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::collections::BTreeSet;
use std::io::Write;
use std::path::PathBuf;

/// Who produced a proposal.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ProposalOrigin {
    /// A language model (any provider, any agent).
    Model,
    /// A human operator via an explicit CLI command.
    Operator,
    /// Automated host code (for example an inbox auto-reply).
    System,
}

/// What a proposal would do.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ActionKind {
    /// Send a payload through a Rig transport adapter. `destination` is the
    /// peer address for addressed transports (LXMF) and `None` otherwise.
    TransportSend {
        transport: String,
        #[serde(skip_serializing_if = "Option::is_none")]
        destination: Option<String>,
    },
    /// Key a radio transmitter. Parameters are set by a human operator.
    RadioTransmit {
        /// Licensed callsign; also the Skybridge station id on air.
        callsign: String,
        /// USB dial (suppressed-carrier) frequency in Hz.
        frequency_hz: u64,
        /// Transmit power in watts.
        power_w: u16,
    },
    /// Modify authoritative configuration state.
    ConfigWrite { key: String },
}

impl ActionKind {
    fn label(&self) -> String {
        match self {
            Self::TransportSend {
                transport,
                destination: None,
            } => format!("transport_send:{transport}"),
            // Only a validated address is recorded; anything else is untrusted text.
            Self::TransportSend {
                transport,
                destination: Some(destination),
            } if is_lxmf_address(destination) => {
                format!("transport_send:{transport}:{destination}")
            }
            Self::TransportSend { transport, .. } => {
                format!("transport_send:{transport}:(invalid destination)")
            }
            Self::RadioTransmit {
                callsign,
                frequency_hz,
                power_w,
            } => {
                let callsign = if is_callsign(callsign) {
                    callsign.as_str()
                } else {
                    "(invalid callsign)"
                };
                format!("radio_transmit:{callsign}@{frequency_hz}Hz/{power_w}W")
            }
            Self::ConfigWrite { key } => format!("config_write:{key}"),
        }
    }

    /// Whether the action has effects outside this process.
    fn is_external(&self) -> bool {
        match self {
            Self::TransportSend { transport, .. } => transport != "local",
            Self::RadioTransmit { .. } | Self::ConfigWrite { .. } => true,
        }
    }
}

/// A model's opinion about a proposal. Recorded for audit only.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ModelAssessment {
    pub recommendation: String,
    pub confidence: f64,
}

/// A proposed action.
#[derive(Debug, Clone, PartialEq)]
pub struct ActionProposal {
    pub id: String,
    pub origin: ProposalOrigin,
    pub kind: ActionKind,
    pub payload: Vec<u8>,
    pub model_assessment: Option<ModelAssessment>,
}

impl ActionProposal {
    pub fn new(origin: ProposalOrigin, kind: ActionKind, payload: impl Into<Vec<u8>>) -> Self {
        Self {
            id: uuid::Uuid::new_v4().to_string(),
            origin,
            kind,
            payload: payload.into(),
            model_assessment: None,
        }
    }

    #[must_use]
    pub fn with_model_assessment(mut self, recommendation: &str, confidence: f64) -> Self {
        self.model_assessment = Some(ModelAssessment {
            recommendation: recommendation.to_string(),
            confidence,
        });
        self
    }
}

/// Operator-configured radio limits (`[rig.radio]` callsign and power).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RadioPolicy {
    pub licensed_callsign: String,
    pub max_power_w: u16,
}

/// Host policy for the boundary.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ActionPolicy {
    pub max_payload_bytes: usize,
    /// Transport ids whose adapters can send in this build.
    pub sendable_transports: BTreeSet<String>,
    /// Radio limits; without them every RF transmit is rejected.
    pub radio: Option<RadioPolicy>,
}

impl ActionPolicy {
    pub fn new(max_payload_bytes: usize) -> Self {
        Self {
            max_payload_bytes,
            sendable_transports: BTreeSet::new(),
            radio: None,
        }
    }

    #[must_use]
    pub fn with_radio(mut self, radio: RadioPolicy) -> Self {
        self.radio = Some(radio);
        self
    }

    #[must_use]
    pub fn allow_transport(mut self, transport: &str) -> Self {
        self.sendable_transports.insert(transport.to_string());
        self
    }
}

/// Outcome of one check.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct CheckOutcome {
    pub check: &'static str,
    pub passed: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
}

impl CheckOutcome {
    fn pass(check: &'static str) -> Self {
        Self {
            check,
            passed: true,
            reason: None,
        }
    }

    fn fail(check: &'static str, reason: impl Into<String>) -> Self {
        Self {
            check,
            passed: false,
            reason: Some(reason.into()),
        }
    }
}

/// Final disposition of a proposal.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Disposition {
    Authorized,
    AwaitingHumanAuthorization,
    Rejected,
}

/// Audit record for one proposal. Contains a payload digest, never the payload.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct DispositionRecord {
    pub proposal_id: String,
    pub origin: ProposalOrigin,
    pub action: String,
    pub payload_bytes: usize,
    pub payload_sha256: String,
    pub checks: Vec<CheckOutcome>,
    pub human_authorization_required: bool,
    pub human_authorization_present: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub model_assessment: Option<ModelAssessment>,
    pub disposition: Disposition,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
    pub recorded_at: String,
}

/// A human operator's approval for one specific proposal.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HumanApproval {
    proposal_id: String,
}

impl HumanApproval {
    /// Record that an operator explicitly confirmed `proposal_id` (for
    /// example by answering an interactive prompt). An approval for one
    /// proposal cannot authorize another.
    pub fn confirmed_by_operator(proposal_id: &str) -> Self {
        Self {
            proposal_id: proposal_id.to_string(),
        }
    }
}

/// Private seal: only this module can build an [`AuthorizedAction`].
#[derive(Debug, Clone, PartialEq, Eq)]
struct Seal;

/// Capability token for executing exactly one authorized proposal.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AuthorizedAction {
    proposal_id: String,
    kind: ActionKind,
    payload: Vec<u8>,
    _seal: Seal,
}

impl AuthorizedAction {
    pub fn proposal_id(&self) -> &str {
        &self.proposal_id
    }

    pub fn kind(&self) -> &ActionKind {
        &self.kind
    }

    pub fn payload(&self) -> &[u8] {
        &self.payload
    }

    /// Radio parameters when this token authorizes an RF transmission.
    pub fn radio_transmit(&self) -> Option<(&str, u64, u16)> {
        match &self.kind {
            ActionKind::RadioTransmit {
                callsign,
                frequency_hz,
                power_w,
            } => Some((callsign.as_str(), *frequency_hz, *power_w)),
            _ => None,
        }
    }

    /// Whether this token authorizes a send on `transport`.
    pub fn targets_transport(&self, transport: &str) -> bool {
        matches!(&self.kind, ActionKind::TransportSend { transport: target, .. } if target == transport)
    }

    /// Peer address for addressed transports (validated by the boundary).
    pub fn destination(&self) -> Option<&str> {
        match &self.kind {
            ActionKind::TransportSend { destination, .. } => destination.as_deref(),
            _ => None,
        }
    }
}

/// Append-only JSONL disposition log.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DispositionLog {
    path: PathBuf,
}

impl DispositionLog {
    pub fn new(path: PathBuf) -> Self {
        Self { path }
    }

    pub fn path(&self) -> &std::path::Path {
        &self.path
    }

    fn append(&self, record: &DispositionRecord) -> anyhow::Result<()> {
        if let Some(parent) = self.path.parent() {
            std::fs::create_dir_all(parent)
                .with_context(|| format!("creating {}", parent.display()))?;
        }
        let mut options = std::fs::OpenOptions::new();
        options.create(true).append(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let mut file = options
            .open(&self.path)
            .with_context(|| format!("opening {}", self.path.display()))?;
        let mut line = serde_json::to_vec(record)?;
        line.push(b'\n');
        file.write_all(&line)?;
        file.flush()?;
        Ok(())
    }
}

/// The boundary itself.
#[derive(Debug, Clone)]
pub struct ActionBoundary {
    policy: ActionPolicy,
    log: Option<DispositionLog>,
}

/// Unicode bidirectional controls that can disguise text ("Trojan Source").
fn is_bidi_control(c: char) -> bool {
    matches!(c, '\u{202A}'..='\u{202E}' | '\u{2066}'..='\u{2069}')
}

/// Shared plaintext rule: UTF-8, no control characters except `\n`/`\t`,
/// no bidirectional overrides.
pub fn validate_plaintext(payload: &[u8]) -> Result<&str, String> {
    let text = std::str::from_utf8(payload).map_err(|_| "payload is not UTF-8 text".to_string())?;
    if let Some(bad) = text
        .chars()
        .find(|c| (c.is_control() && *c != '\n' && *c != '\t') || is_bidi_control(*c))
    {
        return Err(format!(
            "payload contains disallowed character U+{:04X}",
            bad as u32
        ));
    }
    Ok(text)
}

/// Whether RF transmit is compiled into this binary.
pub const RF_TRANSMIT_COMPILED: bool = cfg!(feature = "rig-rf-transmit");

/// Width of the USB channel that must fit inside a band (Hz).
pub const RF_CHANNEL_WIDTH_HZ: u64 = 3_000;

/// Amateur HF allocation used as an outer bound for RF transmit.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Band {
    pub name: &'static str,
    pub low_hz: u64,
    pub high_hz: u64,
}

/// Conservative HF band plan: the parts of each amateur allocation that are
/// common to ITU Regions 1, 2 and 3. 60 m is excluded (channelized and
/// nationally variable). This is an outer bound, not a grant: the operator's
/// licence class and national rules may be narrower.
#[rustfmt::skip]
pub const RF_BAND_PLAN: &[Band] = &[
    Band { name: "160m", low_hz: 1_810_000, high_hz: 1_850_000 },
    Band { name: "80m", low_hz: 3_500_000, high_hz: 3_800_000 },
    Band { name: "40m", low_hz: 7_000_000, high_hz: 7_200_000 },
    Band { name: "30m", low_hz: 10_100_000, high_hz: 10_150_000 },
    Band { name: "20m", low_hz: 14_000_000, high_hz: 14_350_000 },
    Band { name: "17m", low_hz: 18_068_000, high_hz: 18_168_000 },
    Band { name: "15m", low_hz: 21_000_000, high_hz: 21_450_000 },
    Band { name: "12m", low_hz: 24_890_000, high_hz: 24_990_000 },
    Band { name: "10m", low_hz: 28_000_000, high_hz: 29_700_000 },
];

/// Band whose limits contain the whole USB channel at `dial_hz`.
pub fn band_for(dial_hz: u64) -> Option<&'static Band> {
    RF_BAND_PLAN.iter().find(|band| {
        dial_hz >= band.low_hz && dial_hz.saturating_add(RF_CHANNEL_WIDTH_HZ) <= band.high_hz
    })
}

/// Callsign shape check shared with config validation.
pub use crate::config::is_amateur_callsign as is_callsign;

fn radio_checks(
    policy: Option<&RadioPolicy>,
    callsign: &str,
    frequency_hz: u64,
    power_w: u16,
) -> Vec<CheckOutcome> {
    let Some(policy) = policy else {
        return vec![CheckOutcome::fail(
            "validation.radio_configured",
            "no licensed callsign and power limit configured ([rig.radio] callsign, max_power_w)",
        )];
    };
    let callsign_check = if !is_callsign(callsign) {
        CheckOutcome::fail("validation.callsign", "callsign is malformed")
    } else if callsign != policy.licensed_callsign {
        CheckOutcome::fail(
            "validation.callsign",
            "callsign does not match the configured licensed callsign",
        )
    } else {
        CheckOutcome::pass("validation.callsign")
    };
    let frequency = match band_for(frequency_hz) {
        Some(_) => CheckOutcome::pass("validation.frequency"),
        None => CheckOutcome::fail(
            "validation.frequency",
            format!(
                "{frequency_hz} Hz: the {RF_CHANNEL_WIDTH_HZ} Hz USB channel is not inside the permitted band plan"
            ),
        ),
    };
    let power = if power_w == 0 || power_w > policy.max_power_w {
        CheckOutcome::fail(
            "validation.power",
            format!("{power_w} W is outside 1-{} W", policy.max_power_w),
        )
    } else {
        CheckOutcome::pass("validation.power")
    };
    vec![callsign_check, frequency, power]
}

/// Transports that deliver to an explicit peer address.
const ADDRESSED_TRANSPORTS: &[&str] = &["lxmf"];

/// LXMF/Reticulum destination hash: 16 bytes as 32 lowercase hex characters.
pub fn is_lxmf_address(value: &str) -> bool {
    value.len() == 32
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

fn destination_check(transport: &str, destination: Option<&str>) -> CheckOutcome {
    const CHECK: &str = "validation.destination";
    match (ADDRESSED_TRANSPORTS.contains(&transport), destination) {
        (true, Some(address)) if is_lxmf_address(address) => CheckOutcome::pass(CHECK),
        (true, Some(_)) => CheckOutcome::fail(
            CHECK,
            "destination must be a 32-character lowercase hex LXMF address",
        ),
        (true, None) => CheckOutcome::fail(
            CHECK,
            format!("transport '{transport}' requires a destination"),
        ),
        (false, Some(_)) => CheckOutcome::fail(
            CHECK,
            format!("transport '{transport}' does not take a destination"),
        ),
        (false, None) => CheckOutcome::pass(CHECK),
    }
}

impl ActionBoundary {
    pub fn new(policy: ActionPolicy, log: Option<DispositionLog>) -> Self {
        Self { policy, log }
    }

    pub fn policy(&self) -> &ActionPolicy {
        &self.policy
    }

    fn policy_checks(&self, proposal: &ActionProposal) -> Vec<CheckOutcome> {
        let permitted = match (&proposal.kind, proposal.origin) {
            (ActionKind::RadioTransmit { .. }, _) if !RF_TRANSMIT_COMPILED => CheckOutcome::fail(
                "policy.action_permitted",
                "RF transmit is not compiled into this build (Cargo feature rig-rf-transmit)",
            ),
            (ActionKind::RadioTransmit { .. }, ProposalOrigin::Model | ProposalOrigin::System) => {
                CheckOutcome::fail(
                    "policy.action_permitted",
                    "RF transmit parameters must come from a human operator, never a model or host code",
                )
            }
            (ActionKind::ConfigWrite { .. }, ProposalOrigin::Model) => CheckOutcome::fail(
                "policy.action_permitted",
                "models may not modify authoritative configuration",
            ),
            _ => CheckOutcome::pass("policy.action_permitted"),
        };
        let mut checks = vec![permitted];
        if let ActionKind::TransportSend { transport, .. } = &proposal.kind {
            checks.push(if self.policy.sendable_transports.contains(transport) {
                CheckOutcome::pass("policy.transport_sendable")
            } else {
                CheckOutcome::fail(
                    "policy.transport_sendable",
                    format!("transport '{transport}' cannot send in this build"),
                )
            });
        }
        checks
    }

    fn deterministic_checks(&self, proposal: &ActionProposal) -> Vec<CheckOutcome> {
        let len = proposal.payload.len();
        let size = if len == 0 {
            CheckOutcome::fail("validation.payload_size", "payload is empty")
        } else if len > self.policy.max_payload_bytes {
            CheckOutcome::fail(
                "validation.payload_size",
                format!(
                    "payload is {len} bytes; limit is {}",
                    self.policy.max_payload_bytes
                ),
            )
        } else {
            CheckOutcome::pass("validation.payload_size")
        };
        let text = match validate_plaintext(&proposal.payload) {
            Ok(_) => CheckOutcome::pass("validation.plaintext"),
            Err(reason) => CheckOutcome::fail("validation.plaintext", reason),
        };
        let id = if uuid::Uuid::parse_str(&proposal.id).is_ok() {
            CheckOutcome::pass("validation.proposal_id")
        } else {
            CheckOutcome::fail("validation.proposal_id", "proposal id is not a UUID")
        };
        let mut checks = vec![id, size, text];
        match &proposal.kind {
            ActionKind::TransportSend {
                transport,
                destination,
            } => checks.push(destination_check(transport, destination.as_deref())),
            ActionKind::RadioTransmit {
                callsign,
                frequency_hz,
                power_w,
            } => checks.extend(radio_checks(
                self.policy.radio.as_ref(),
                callsign,
                *frequency_hz,
                *power_w,
            )),
            ActionKind::ConfigWrite { .. } => {}
        }
        checks
    }

    /// External actions from a non-operator need a human; RF transmit
    /// always does, whoever proposed it.
    fn requires_human(proposal: &ActionProposal) -> bool {
        matches!(proposal.kind, ActionKind::RadioTransmit { .. })
            || (proposal.origin != ProposalOrigin::Operator && proposal.kind.is_external())
    }

    /// Evaluate a proposal. Returns the recorded disposition and, only when
    /// authorized, the token that a transport adapter will accept.
    pub fn submit(
        &self,
        proposal: ActionProposal,
        approval: Option<&HumanApproval>,
    ) -> (DispositionRecord, Option<AuthorizedAction>) {
        let mut checks = self.policy_checks(&proposal);
        checks.extend(self.deterministic_checks(&proposal));
        let failed = checks.iter().find(|check| !check.passed).cloned();

        let human_required = Self::requires_human(&proposal);
        let approval_matches = approval.is_some_and(|a| a.proposal_id == proposal.id);

        let (mut disposition, mut reason) = match (&failed, human_required, approval_matches) {
            (Some(check), _, _) => (
                Disposition::Rejected,
                Some(format!(
                    "{} failed: {}",
                    check.check,
                    check.reason.clone().unwrap_or_default()
                )),
            ),
            (None, true, false) => (
                Disposition::AwaitingHumanAuthorization,
                Some(
                    if matches!(proposal.kind, ActionKind::RadioTransmit { .. }) {
                        "RF transmit requires the operator's interactive confirmation"
                    } else {
                        "external action proposed by a non-operator requires human authorization"
                    }
                    .into(),
                ),
            ),
            (None, _, _) => (Disposition::Authorized, None),
        };

        let digest = hex::encode(Sha256::digest(&proposal.payload));
        let mut record = DispositionRecord {
            proposal_id: proposal.id.clone(),
            origin: proposal.origin,
            action: proposal.kind.label(),
            payload_bytes: proposal.payload.len(),
            payload_sha256: digest,
            checks,
            human_authorization_required: human_required,
            human_authorization_present: approval_matches,
            model_assessment: proposal.model_assessment.clone(),
            disposition,
            reason: reason.clone(),
            recorded_at: chrono::Utc::now().to_rfc3339(),
        };

        if let Some(log) = &self.log {
            if let Err(error) = log.append(&record) {
                disposition = Disposition::Rejected;
                reason = Some(format!("disposition could not be recorded: {error}"));
                record.disposition = disposition;
                record.reason = reason;
                return (record, None);
            }
        }

        let token = (disposition == Disposition::Authorized).then(|| AuthorizedAction {
            proposal_id: proposal.id,
            kind: proposal.kind,
            payload: proposal.payload,
            _seal: Seal,
        });
        (record, token)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn boundary() -> ActionBoundary {
        ActionBoundary::new(
            ActionPolicy::new(64)
                .allow_transport("local")
                .allow_transport("skybridge"),
            None,
        )
    }

    fn send(transport: &str) -> ActionKind {
        ActionKind::TransportSend {
            transport: transport.into(),
            destination: None,
        }
    }

    #[test]
    fn operator_send_passing_all_checks_is_authorized() {
        let proposal = ActionProposal::new(ProposalOrigin::Operator, send("skybridge"), "hello");
        let (record, token) = boundary().submit(proposal, None);
        assert_eq!(record.disposition, Disposition::Authorized);
        let token = token.unwrap();
        assert!(token.targets_transport("skybridge"));
        assert!(!token.targets_transport("local"));
        assert_eq!(token.payload(), b"hello");
    }

    #[test]
    fn model_external_action_waits_for_human_authorization() {
        let proposal = ActionProposal::new(ProposalOrigin::Model, send("skybridge"), "hello")
            .with_model_assessment("send now", 0.99);
        let (record, token) = boundary().submit(proposal.clone(), None);
        assert_eq!(record.disposition, Disposition::AwaitingHumanAuthorization);
        assert!(token.is_none());

        let wrong = HumanApproval::confirmed_by_operator("some-other-proposal");
        let (record, token) = boundary().submit(proposal.clone(), Some(&wrong));
        assert_eq!(record.disposition, Disposition::AwaitingHumanAuthorization);
        assert!(token.is_none());

        let approval = HumanApproval::confirmed_by_operator(&proposal.id);
        let (record, token) = boundary().submit(proposal, Some(&approval));
        assert_eq!(record.disposition, Disposition::Authorized);
        assert!(token.is_some());
    }

    #[test]
    fn model_assessment_cannot_override_failed_deterministic_check() {
        let proposal =
            ActionProposal::new(ProposalOrigin::Model, send("skybridge"), vec![b'x'; 65])
                .with_model_assessment("approve: payload is fine", 1.0);
        let approval = HumanApproval::confirmed_by_operator(&proposal.id);
        let (record, token) = boundary().submit(proposal, Some(&approval));
        assert_eq!(record.disposition, Disposition::Rejected);
        assert!(token.is_none());
        assert!(record.reason.unwrap().contains("validation.payload_size"));
        assert!(
            record.model_assessment.is_some(),
            "assessment is still recorded"
        );
    }

    fn radio(callsign: &str, frequency_hz: u64, power_w: u16) -> ActionKind {
        ActionKind::RadioTransmit {
            callsign: callsign.into(),
            frequency_hz,
            power_w,
        }
    }

    fn radio_boundary() -> ActionBoundary {
        ActionBoundary::new(
            ActionPolicy::new(64).with_radio(RadioPolicy {
                licensed_callsign: "N0CALL".into(),
                max_power_w: 50,
            }),
            None,
        )
    }

    #[cfg(not(feature = "rig-rf-transmit"))]
    #[test]
    fn radio_transmit_is_rejected_when_not_compiled_in() {
        for origin in [
            ProposalOrigin::Operator,
            ProposalOrigin::Model,
            ProposalOrigin::System,
        ] {
            let proposal = ActionProposal::new(origin, radio("N0CALL", 14_100_000, 10), "CQ CQ");
            let approval = HumanApproval::confirmed_by_operator(&proposal.id);
            let (record, token) = radio_boundary().submit(proposal, Some(&approval));
            assert_eq!(record.disposition, Disposition::Rejected);
            assert!(token.is_none());
            assert!(record.reason.unwrap().contains("not compiled"));
        }
    }

    #[test]
    fn band_plan_keeps_the_whole_channel_inside_a_band() {
        assert_eq!(band_for(14_100_000).map(|b| b.name), Some("20m"));
        assert_eq!(band_for(14_000_000).map(|b| b.name), Some("20m"));
        assert!(
            band_for(14_348_000).is_none(),
            "channel would cross the band edge"
        );
        assert!(band_for(13_999_999).is_none());
        assert!(band_for(5_357_000).is_none(), "60 m is excluded");
        assert!(band_for(7_250_000).is_none(), "region 2 only");
        assert!(band_for(0).is_none() && band_for(u64::MAX).is_none());
        for band in RF_BAND_PLAN {
            assert!(band.low_hz + RF_CHANNEL_WIDTH_HZ <= band.high_hz);
        }
    }

    #[test]
    fn callsign_shape_is_strict() {
        for good in ["N0CALL", "K1ABC", "N0CALL/P", "2E0XYZ"] {
            assert!(is_callsign(good), "{good}");
        }
        for bad in [
            "",
            "AB",
            "n0call",
            "NOCALL",
            "12345",
            "N0CALL-10X",
            "N0 CALL",
        ] {
            assert!(!is_callsign(bad), "{bad}");
        }
    }

    #[test]
    fn radio_parameters_are_checked_deterministically() {
        let bad = [
            radio("K1ABC", 14_100_000, 10),
            radio("N0CALL", 14_349_000, 10),
            radio("N0CALL", 5_357_000, 10),
            radio("N0CALL", 14_100_000, 0),
            radio("N0CALL", 14_100_000, 51),
        ];
        for kind in bad {
            let proposal = ActionProposal::new(ProposalOrigin::Operator, kind.clone(), "CQ");
            let approval = HumanApproval::confirmed_by_operator(&proposal.id);
            let (record, token) = radio_boundary().submit(proposal, Some(&approval));
            assert_eq!(record.disposition, Disposition::Rejected, "{kind:?}");
            assert!(token.is_none());
            assert!(
                record
                    .checks
                    .iter()
                    .any(|c| !c.passed && c.check.starts_with("validation.")),
                "{kind:?}: {:?}",
                record.checks
            );
        }
        // Without configured limits nothing can be authorized.
        let proposal = ActionProposal::new(
            ProposalOrigin::Operator,
            radio("N0CALL", 14_100_000, 10),
            "CQ",
        );
        let approval = HumanApproval::confirmed_by_operator(&proposal.id);
        let (record, _) = boundary().submit(proposal, Some(&approval));
        assert_eq!(record.disposition, Disposition::Rejected);
        assert!(
            record
                .checks
                .iter()
                .any(|c| c.check == "validation.radio_configured")
        );
    }

    #[cfg(feature = "rig-rf-transmit")]
    #[test]
    fn operator_rf_transmit_needs_a_matching_confirmation() {
        let proposal = ActionProposal::new(
            ProposalOrigin::Operator,
            radio("N0CALL", 14_100_000, 10),
            "CQ",
        );
        let (record, token) = radio_boundary().submit(proposal.clone(), None);
        assert_eq!(record.disposition, Disposition::AwaitingHumanAuthorization);
        assert!(token.is_none());
        let wrong = HumanApproval::confirmed_by_operator("other");
        assert!(
            radio_boundary()
                .submit(proposal.clone(), Some(&wrong))
                .1
                .is_none()
        );
        let approval = HumanApproval::confirmed_by_operator(&proposal.id);
        let (record, token) = radio_boundary().submit(proposal, Some(&approval));
        assert_eq!(record.disposition, Disposition::Authorized);
        assert_eq!(record.action, "radio_transmit:N0CALL@14100000Hz/10W");
        assert_eq!(
            token.unwrap().radio_transmit(),
            Some(("N0CALL", 14_100_000, 10))
        );
    }

    #[cfg(feature = "rig-rf-transmit")]
    #[test]
    fn models_and_host_code_can_never_transmit() {
        for origin in [ProposalOrigin::Model, ProposalOrigin::System] {
            let proposal = ActionProposal::new(origin, radio("N0CALL", 14_100_000, 10), "CQ")
                .with_model_assessment("transmit now", 1.0);
            let approval = HumanApproval::confirmed_by_operator(&proposal.id);
            let (record, token) = radio_boundary().submit(proposal, Some(&approval));
            assert_eq!(record.disposition, Disposition::Rejected);
            assert!(token.is_none());
        }
    }

    #[test]
    fn models_cannot_write_authoritative_config() {
        let proposal = ActionProposal::new(
            ProposalOrigin::Model,
            ActionKind::ConfigWrite {
                key: "rig.privacy".into(),
            },
            "hosted",
        );
        let approval = HumanApproval::confirmed_by_operator(&proposal.id);
        let (record, token) = boundary().submit(proposal, Some(&approval));
        assert_eq!(record.disposition, Disposition::Rejected);
        assert!(token.is_none());
    }

    #[test]
    fn unsendable_transport_and_bad_text_are_rejected() {
        let (record, token) = boundary().submit(
            ActionProposal::new(ProposalOrigin::Operator, send("reticulum"), "hi"),
            None,
        );
        assert_eq!(record.disposition, Disposition::Rejected);
        assert!(token.is_none());

        for payload in [
            &b"\xff\xfe"[..],
            b"bell\x07",
            "evil\u{202E}txt".as_bytes(),
            b"",
        ] {
            let (record, token) = boundary().submit(
                ActionProposal::new(ProposalOrigin::Operator, send("local"), payload),
                None,
            );
            assert_eq!(record.disposition, Disposition::Rejected, "{payload:?}");
            assert!(token.is_none());
        }
    }

    #[test]
    fn addressed_sends_require_a_valid_destination() {
        let boundary = ActionBoundary::new(
            ActionPolicy::new(64)
                .allow_transport("lxmf")
                .allow_transport("local"),
            None,
        );
        let kind = |transport: &str, destination: Option<&str>| ActionKind::TransportSend {
            transport: transport.into(),
            destination: destination.map(str::to_string),
        };
        let cases = [
            (kind("lxmf", None), false),
            (kind("lxmf", Some("not-a-hash")), false),
            (
                kind("lxmf", Some("0123456789ABCDEF0123456789ABCDEF")),
                false,
            ),
            (kind("lxmf", Some("0123456789abcdef0123456789abcde")), false),
            (
                kind("local", Some("0123456789abcdef0123456789abcdef")),
                false,
            ),
            (kind("lxmf", Some("0123456789abcdef0123456789abcdef")), true),
        ];
        for (kind, expected) in cases {
            let (record, token) = boundary.submit(
                ActionProposal::new(ProposalOrigin::Operator, kind.clone(), "hi"),
                None,
            );
            assert_eq!(token.is_some(), expected, "{kind:?}: {:?}", record.reason);
            assert!(!record.action.contains("not-a-hash"), "{}", record.action);
            if let Some(token) = token {
                assert_eq!(
                    token.destination(),
                    Some("0123456789abcdef0123456789abcdef")
                );
                assert_eq!(
                    record.action,
                    "transport_send:lxmf:0123456789abcdef0123456789abcdef"
                );
            }
        }
    }

    #[test]
    fn local_loopback_from_system_needs_no_human() {
        let (record, token) = boundary().submit(
            ActionProposal::new(ProposalOrigin::System, send("local"), "PONG"),
            None,
        );
        assert_eq!(record.disposition, Disposition::Authorized);
        assert!(token.is_some());
    }

    #[test]
    fn dispositions_are_recorded_without_payload() {
        let dir = tempfile::tempdir().unwrap();
        let log = DispositionLog::new(dir.path().join("rig/dispositions.jsonl"));
        let boundary = ActionBoundary::new(
            ActionPolicy::new(64).allow_transport("local"),
            Some(log.clone()),
        );
        boundary.submit(
            ActionProposal::new(ProposalOrigin::Operator, send("local"), "secret-note"),
            None,
        );
        boundary.submit(
            ActionProposal::new(ProposalOrigin::Model, radio("N0CALL", 14_100_000, 5), "x"),
            None,
        );
        let contents = std::fs::read_to_string(log.path()).unwrap();
        let lines: Vec<_> = contents.lines().collect();
        assert_eq!(lines.len(), 2);
        assert!(!contents.contains("secret-note"));
        let first: serde_json::Value = serde_json::from_str(lines[0]).unwrap();
        assert_eq!(first["disposition"], "authorized");
        assert_eq!(first["payload_bytes"], 11);
        let second: serde_json::Value = serde_json::from_str(lines[1]).unwrap();
        assert_eq!(second["disposition"], "rejected");
    }

    #[test]
    fn unrecordable_disposition_fails_closed() {
        let dir = tempfile::tempdir().unwrap();
        let blocker = dir.path().join("not-a-dir");
        std::fs::write(&blocker, "file").unwrap();
        let boundary = ActionBoundary::new(
            ActionPolicy::new(64).allow_transport("local"),
            Some(DispositionLog::new(blocker.join("dispositions.jsonl"))),
        );
        let (record, token) = boundary.submit(
            ActionProposal::new(ProposalOrigin::Operator, send("local"), "hi"),
            None,
        );
        assert_eq!(record.disposition, Disposition::Rejected);
        assert!(token.is_none());
        assert!(record.reason.unwrap().contains("could not be recorded"));
    }
}
