//! Human approval registry for high-stakes actions.
//!
//! This registry tracks operator-approved requests and enforces a strict
//! `Pending -> Approved` transition guarded by detached signatures over a
//! canonical request digest.

use crate::verifiable_intent::crypto::{b64u_decode, b64u_encode, sha256};
use anyhow::{anyhow, bail};
use ring::signature;
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use std::sync::{Mutex, OnceLock};
use std::time::{SystemTime, UNIX_EPOCH};

/// Current approval lifecycle state for a high-stakes request.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ApprovalState {
    Pending,
    Approved,
    Rejected,
    Expired,
}

/// Coarse risk class carried by an approval request.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RiskClass {
    PhysicalBroadcast,
    HighCostInference,
    HighStakes,
}

/// Request submitted by an autonomous agent for a high-stakes action.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ApprovalRequest {
    pub request_id: String,
    pub requester_agent_id: String,
    pub requested_action: String,
    pub risk_class: RiskClass,
    pub timestamp_unix: i64,
    pub expires_at_unix: i64,
    pub nonce: String,
    pub request_hash: String,
}

impl ApprovalRequest {
    /// Build a canonical request with a deterministic digest.
    pub fn new(
        request_id: impl Into<String>,
        requester_agent_id: impl Into<String>,
        requested_action: impl Into<String>,
        risk_class: RiskClass,
        ttl_secs: i64,
        nonce: impl Into<String>,
    ) -> anyhow::Result<Self> {
        let timestamp_unix = unix_timestamp_now()?;
        let expires_at_unix = timestamp_unix
            .checked_add(ttl_secs)
            .ok_or_else(|| anyhow!("ttl overflow"))?;
        let mut req = Self {
            request_id: request_id.into(),
            requester_agent_id: requester_agent_id.into(),
            requested_action: requested_action.into(),
            risk_class,
            timestamp_unix,
            expires_at_unix,
            nonce: nonce.into(),
            request_hash: String::new(),
        };
        req.request_hash = req.compute_request_hash();
        Ok(req)
    }

    fn canonical_signing_text(&self) -> String {
        format!(
            "request_id={}\nrequester_agent_id={}\nrequested_action={}\nrisk_class={:?}\ntimestamp_unix={}\nexpires_at_unix={}\nnonce={}",
            self.request_id,
            self.requester_agent_id,
            self.requested_action,
            self.risk_class,
            self.timestamp_unix,
            self.expires_at_unix,
            self.nonce,
        )
    }

    pub fn compute_request_hash(&self) -> String {
        b64u_encode(&sha256(self.canonical_signing_text().as_bytes()))
    }

    pub fn is_expired(&self, now_unix: i64) -> bool {
        now_unix > self.expires_at_unix
    }
}

/// Detached operator signature over a canonical request digest.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OperatorApprovalPayload {
    pub request_id: String,
    pub operator_id: String,
    pub request_hash: String,
    pub signed_at_unix: i64,
    /// Base64url-encoded ES256 signature over `request_hash` bytes.
    pub signature_b64u: String,
}

impl OperatorApprovalPayload {
    pub fn verify_signature(&self, operator_public_key_bytes: &[u8]) -> anyhow::Result<()> {
        let sig_bytes = b64u_decode(&self.signature_b64u)
            .map_err(|e| anyhow!("signature decode failed: {e}"))?;
        let verifier = signature::UnparsedPublicKey::new(
            &signature::ECDSA_P256_SHA256_FIXED,
            operator_public_key_bytes,
        );
        verifier
            .verify(self.request_hash.as_bytes(), &sig_bytes)
            .map_err(|_| anyhow!("invalid operator signature"))
    }
}

#[derive(Debug, Clone)]
struct ApprovalRecord {
    request: ApprovalRequest,
    state: ApprovalState,
    operator_id: Option<String>,
    approved_at_unix: Option<i64>,
}

/// In-memory approval registry for operator-gated execution.
#[derive(Debug, Default)]
pub struct ApprovalRegistry {
    requests: HashMap<String, ApprovalRecord>,
    seen_nonces: HashSet<String>,
}

impl ApprovalRegistry {
    pub fn submit(&mut self, request: ApprovalRequest) -> anyhow::Result<()> {
        if self.requests.contains_key(&request.request_id) {
            bail!("duplicate request_id: {}", request.request_id);
        }
        if !self.seen_nonces.insert(request.nonce.clone()) {
            bail!("nonce replay detected");
        }

        self.requests.insert(
            request.request_id.clone(),
            ApprovalRecord {
                request,
                state: ApprovalState::Pending,
                operator_id: None,
                approved_at_unix: None,
            },
        );
        Ok(())
    }

    pub fn verify_and_approve(
        &mut self,
        payload: &OperatorApprovalPayload,
        operator_public_key_bytes: &[u8],
    ) -> anyhow::Result<()> {
        let now = unix_timestamp_now()?;
        let record = self
            .requests
            .get_mut(&payload.request_id)
            .ok_or_else(|| anyhow!("unknown request_id: {}", payload.request_id))?;

        if record.state != ApprovalState::Pending {
            bail!("request {} is not pending", payload.request_id);
        }

        if record.request.is_expired(now) {
            record.state = ApprovalState::Expired;
            bail!("request {} expired", payload.request_id);
        }

        if payload.request_hash != record.request.request_hash {
            bail!("request hash mismatch");
        }

        payload.verify_signature(operator_public_key_bytes)?;

        record.state = ApprovalState::Approved;
        record.operator_id = Some(payload.operator_id.clone());
        record.approved_at_unix = Some(payload.signed_at_unix);
        Ok(())
    }

    pub fn can_execute(&mut self, request_id: &str) -> anyhow::Result<()> {
        let now = unix_timestamp_now()?;
        let record = self
            .requests
            .get_mut(request_id)
            .ok_or_else(|| anyhow!("missing approval request: {request_id}"))?;

        if record.state == ApprovalState::Pending && record.request.is_expired(now) {
            record.state = ApprovalState::Expired;
        }

        if record.state != ApprovalState::Approved {
            bail!(
                "execution blocked: request_id {request_id} is {:?}",
                record.state
            );
        }

        Ok(())
    }

    pub fn state(&self, request_id: &str) -> Option<ApprovalState> {
        self.requests.get(request_id).map(|r| r.state)
    }
}

/// High-stakes classes currently requiring explicit operator approval.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HighStakesClass {
    PhysicalBroadcast,
    HighCostTribeV2Inference,
}

pub fn classify_high_stakes(tool_name: &str, action: &str) -> Option<HighStakesClass> {
    match (tool_name, action) {
        // Physical broadcast/actuation through hardware peripheral channels.
        ("gpio_write" | "arduino_upload", _) => Some(HighStakesClass::PhysicalBroadcast),
        // Costly model inference path in TRIBE v2.
        ("tribev2_predict", "predict") => Some(HighStakesClass::HighCostTribeV2Inference),
        _ => None,
    }
}

pub fn ensure_high_stakes_approved(
    args: &serde_json::Value,
    tool_name: &str,
    action: &str,
) -> anyhow::Result<()> {
    if classify_high_stakes(tool_name, action).is_none() {
        return Ok(());
    }

    let request_id = args
        .get("approval_request_id")
        .and_then(serde_json::Value::as_str)
        .ok_or_else(|| anyhow!("missing required 'approval_request_id' for high-stakes action"))?;

    let mut registry = global_approval_registry()
        .lock()
        .map_err(|_| anyhow!("approval registry lock poisoned"))?;
    registry.can_execute(request_id)
}

pub fn global_approval_registry() -> &'static Mutex<ApprovalRegistry> {
    static REGISTRY: OnceLock<Mutex<ApprovalRegistry>> = OnceLock::new();
    REGISTRY.get_or_init(|| Mutex::new(ApprovalRegistry::default()))
}

fn unix_timestamp_now() -> anyhow::Result<i64> {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|e| anyhow!("system clock error: {e}"))?;
    i64::try_from(now.as_secs()).map_err(|_| anyhow!("timestamp overflow"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use ring::rand::SystemRandom;
    use ring::signature::{EcdsaKeyPair, KeyPair, ECDSA_P256_SHA256_FIXED_SIGNING};

    fn generate_keypair() -> EcdsaKeyPair {
        let rng = SystemRandom::new();
        let pkcs8 = EcdsaKeyPair::generate_pkcs8(&ECDSA_P256_SHA256_FIXED_SIGNING, &rng).unwrap();
        EcdsaKeyPair::from_pkcs8(&ECDSA_P256_SHA256_FIXED_SIGNING, pkcs8.as_ref(), &rng).unwrap()
    }

    fn sign_payload(request_hash: &str, key_pair: &EcdsaKeyPair) -> String {
        let rng = SystemRandom::new();
        let sig = key_pair.sign(&rng, request_hash.as_bytes()).unwrap();
        b64u_encode(sig.as_ref())
    }

    #[test]
    fn invalid_signature_rejected() {
        let key_pair = generate_keypair();
        let other_key = generate_keypair();
        let request = ApprovalRequest::new(
            "req-1",
            "agent-a",
            "tribev2_predict:text",
            RiskClass::HighCostInference,
            120,
            "nonce-1",
        )
        .unwrap();

        let payload = OperatorApprovalPayload {
            request_id: request.request_id.clone(),
            operator_id: "op-1".into(),
            request_hash: request.request_hash.clone(),
            signed_at_unix: request.timestamp_unix,
            signature_b64u: sign_payload(&request.request_hash, &other_key),
        };

        let mut registry = ApprovalRegistry::default();
        registry.submit(request).unwrap();

        let err = registry
            .verify_and_approve(&payload, key_pair.public_key().as_ref())
            .unwrap_err();
        assert!(err.to_string().contains("invalid operator signature"));
        assert_eq!(registry.state("req-1"), Some(ApprovalState::Pending));
    }

    #[test]
    fn expired_pending_request_rejected() {
        let key_pair = generate_keypair();
        let mut request = ApprovalRequest::new(
            "req-exp",
            "agent-a",
            "gpio_write:pin13",
            RiskClass::PhysicalBroadcast,
            120,
            "nonce-exp",
        )
        .unwrap();
        request.expires_at_unix = request.timestamp_unix - 1;
        request.request_hash = request.compute_request_hash();

        let payload = OperatorApprovalPayload {
            request_id: request.request_id.clone(),
            operator_id: "op-1".into(),
            request_hash: request.request_hash.clone(),
            signed_at_unix: request.timestamp_unix,
            signature_b64u: sign_payload(&request.request_hash, &key_pair),
        };

        let mut registry = ApprovalRegistry::default();
        registry.submit(request).unwrap();
        let err = registry
            .verify_and_approve(&payload, key_pair.public_key().as_ref())
            .unwrap_err();
        assert!(err.to_string().contains("expired"));
        assert_eq!(registry.state("req-exp"), Some(ApprovalState::Expired));
    }

    #[test]
    fn replay_protection_blocks_duplicate_nonce_and_request_id() {
        let req1 = ApprovalRequest::new(
            "req-dup",
            "agent-a",
            "gpio_write:pin13",
            RiskClass::PhysicalBroadcast,
            120,
            "nonce-replay",
        )
        .unwrap();
        let req2 = ApprovalRequest::new(
            "req-dup",
            "agent-a",
            "gpio_write:pin13",
            RiskClass::PhysicalBroadcast,
            120,
            "nonce-replay-2",
        )
        .unwrap();
        let req3 = ApprovalRequest::new(
            "req-unique",
            "agent-a",
            "tribev2_predict:text",
            RiskClass::HighCostInference,
            120,
            "nonce-replay",
        )
        .unwrap();

        let mut registry = ApprovalRegistry::default();
        registry.submit(req1).unwrap();

        let dup_id_err = registry.submit(req2).unwrap_err();
        assert!(dup_id_err.to_string().contains("duplicate request_id"));

        let dup_nonce_err = registry.submit(req3).unwrap_err();
        assert!(dup_nonce_err.to_string().contains("nonce replay"));
    }

    #[test]
    fn pending_transitions_to_approved_only_with_valid_signature() {
        let key_pair = generate_keypair();
        let request = ApprovalRequest::new(
            "req-ok",
            "agent-a",
            "gpio_write:pin13=1",
            RiskClass::PhysicalBroadcast,
            120,
            "nonce-ok",
        )
        .unwrap();

        let payload = OperatorApprovalPayload {
            request_id: request.request_id.clone(),
            operator_id: "op-1".into(),
            request_hash: request.request_hash.clone(),
            signed_at_unix: request.timestamp_unix,
            signature_b64u: sign_payload(&request.request_hash, &key_pair),
        };

        let mut registry = ApprovalRegistry::default();
        registry.submit(request).unwrap();
        assert_eq!(registry.state("req-ok"), Some(ApprovalState::Pending));

        registry
            .verify_and_approve(&payload, key_pair.public_key().as_ref())
            .unwrap();
        assert_eq!(registry.state("req-ok"), Some(ApprovalState::Approved));
        registry.can_execute("req-ok").unwrap();
    }
}
