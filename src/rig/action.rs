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
    /// Key a radio or SDR transmitter. Never permitted in this build.
    RadioTransmit,
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
            Self::RadioTransmit => "radio_transmit".into(),
            Self::ConfigWrite { key } => format!("config_write:{key}"),
        }
    }

    /// Whether the action has effects outside this process.
    fn is_external(&self) -> bool {
        match self {
            Self::TransportSend { transport, .. } => transport != "local",
            Self::RadioTransmit | Self::ConfigWrite { .. } => true,
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

/// Host policy for the boundary.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ActionPolicy {
    pub max_payload_bytes: usize,
    /// Transport ids whose adapters can send in this build.
    pub sendable_transports: BTreeSet<String>,
}

impl ActionPolicy {
    pub fn new(max_payload_bytes: usize) -> Self {
        Self {
            max_payload_bytes,
            sendable_transports: BTreeSet::new(),
        }
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
            (ActionKind::RadioTransmit, _) => CheckOutcome::fail(
                "policy.action_permitted",
                "RF transmit is not supported in this build",
            ),
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
        if let ActionKind::TransportSend {
            transport,
            destination,
        } = &proposal.kind
        {
            checks.push(destination_check(transport, destination.as_deref()));
        }
        checks
    }

    fn requires_human(proposal: &ActionProposal) -> bool {
        proposal.origin != ProposalOrigin::Operator && proposal.kind.is_external()
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
                    "external action proposed by a non-operator requires human authorization"
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

    #[test]
    fn radio_transmit_is_always_rejected() {
        for origin in [
            ProposalOrigin::Operator,
            ProposalOrigin::Model,
            ProposalOrigin::System,
        ] {
            let proposal = ActionProposal::new(origin, ActionKind::RadioTransmit, "CQ CQ");
            let approval = HumanApproval::confirmed_by_operator(&proposal.id);
            let (record, token) = boundary().submit(proposal, Some(&approval));
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
            ActionProposal::new(ProposalOrigin::Model, ActionKind::RadioTransmit, "x"),
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
