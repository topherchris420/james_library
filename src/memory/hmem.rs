//! H-MEM memory backend — Rust implementation of the Meterless H-MEM
//! retrieval semantics (<https://github.com/Meterless/Meterless>).
//!
//! Wraps [`SqliteMemory`] for persistence (same pattern as `LucidMemory`)
//! and layers three H-MEM behaviors on top:
//!
//! 1. **8-signal hybrid re-ranking** on recall:
//!    `raw = 0.35·semantic + 0.20·keyword + 0.10·tag + 0.10·domain
//!         + 0.15·entity + 0.05·layer + 0.05·recency − 0.20·superseded`,
//!    `score = clamp01(raw) × confidence`, thresholded at 0.35.
//! 2. **Tier mapping**: `MemoryCategory` maps onto H-MEM layers
//!    (`Core` → long_term, `Daily`/`Custom` → working,
//!    `Conversation` → short_term) for the layer signal.
//! 3. **Append-only trust ledger**: every successful mutation is recorded
//!    in `memory/hmem_trust_ledger.jsonl` with derived provenance and a
//!    SHA-256 content digest (never the raw content). Records are only
//!    appended, never rewritten or pruned by this backend.
//!
//! Signal mapping to R.A.I.N. structures: the inner sqlite hybrid score
//! (vector + BM25, max-normalized across the candidate pool, mirroring
//! `vector::hybrid_merge` normalization) serves as the semantic signal;
//! entry keys serve as tags; namespaces serve as domains; `importance`
//! serves as confidence (unset ⇒ 1.0).

use super::sqlite::SqliteMemory;
use super::traits::{ExportFilter, Memory, MemoryCategory, MemoryEntry, ProceduralMessage};
use async_trait::async_trait;
use chrono::{DateTime, Utc};
use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::{HashMap, HashSet};
use std::io::Write as _;
use std::path::{Path, PathBuf};

// Ranking weights from the Meterless H-MEM specification.
const W_SEMANTIC: f64 = 0.35;
const W_KEYWORD: f64 = 0.20;
const W_TAG: f64 = 0.10;
const W_DOMAIN: f64 = 0.10;
const W_ENTITY: f64 = 0.15;
const W_LAYER: f64 = 0.05;
const W_RECENCY: f64 = 0.05;
const SUPERSEDED_PENALTY: f64 = 0.20;
/// Minimum final score for a candidate to be returned (spec: 0.35).
const SCORE_THRESHOLD: f64 = 0.35;
/// Recency decays with `exp(-age_days / 14)` (spec: ~14-day constant).
const RECENCY_DECAY_DAYS: f64 = 14.0;
/// Keyword signal compares the top-8 tokens of query and content (spec).
const KEYWORD_TOP_TOKENS: usize = 8;
/// Candidate pool bounds for re-ranking: fetch more than requested so the
/// H-MEM formula has room to reorder, without unbounded scans.
const POOL_MIN: usize = 20;
const POOL_MAX: usize = 100;

const LEDGER_FILE: &str = "hmem_trust_ledger.jsonl";

/// One append-only trust-ledger record. Raw content is never stored here —
/// only its SHA-256 digest — so the ledger stays safe to inspect and ship.
#[derive(Debug, Serialize, Deserialize)]
pub struct TrustLedgerRecord {
    pub ts: String,
    pub action: String,
    pub key: String,
    /// Derived provenance: `session:<id>` when session-scoped, else `direct`.
    pub source: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub category: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub namespace: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub session_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub content_sha256: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub affected: Option<usize>,
}

pub struct HmemMemory {
    inner: SqliteMemory,
    ledger_path: PathBuf,
    ledger_lock: Mutex<()>,
}

impl HmemMemory {
    pub fn new(workspace_dir: &Path, inner: SqliteMemory) -> Self {
        Self {
            inner,
            ledger_path: workspace_dir.join("memory").join(LEDGER_FILE),
            ledger_lock: Mutex::new(()),
        }
    }

    /// Path of the append-only trust ledger.
    pub fn ledger_path(&self) -> &Path {
        &self.ledger_path
    }

    fn derive_source(session_id: Option<&str>) -> String {
        match session_id {
            Some(id) if !id.trim().is_empty() => format!("session:{id}"),
            _ => "direct".to_string(),
        }
    }

    fn content_digest(content: &str) -> String {
        hex::encode(Sha256::digest(content.as_bytes()))
    }

    /// Append one record to the trust ledger. Mutations must be audited:
    /// a failed append surfaces as an error to the caller instead of
    /// silently leaving the mutation unrecorded.
    fn append_ledger(&self, record: &TrustLedgerRecord) -> anyhow::Result<()> {
        let line = serde_json::to_string(record)?;
        let _guard = self.ledger_lock.lock();
        if let Some(parent) = self.ledger_path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let mut file = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.ledger_path)?;
        writeln!(file, "{line}")?;
        Ok(())
    }

    fn record_store(
        &self,
        key: &str,
        content: &str,
        category: &MemoryCategory,
        session_id: Option<&str>,
        namespace: Option<&str>,
    ) -> anyhow::Result<()> {
        self.append_ledger(&TrustLedgerRecord {
            ts: Utc::now().to_rfc3339(),
            action: "store".to_string(),
            key: key.to_string(),
            source: Self::derive_source(session_id),
            category: Some(category.to_string()),
            namespace: namespace.map(str::to_string),
            session_id: session_id.map(str::to_string),
            content_sha256: Some(Self::content_digest(content)),
            affected: None,
        })
    }

    fn pool_limit(limit: usize) -> usize {
        limit.saturating_mul(4).clamp(POOL_MIN, POOL_MAX)
    }
}

/// Lowercased alphanumeric tokens (length ≥ 2), deduplicated in order.
fn tokenize(text: &str) -> Vec<String> {
    let mut seen = HashSet::new();
    let mut tokens = Vec::new();
    for raw in text.split(|c: char| !c.is_alphanumeric()) {
        let token = raw.to_lowercase();
        if token.chars().count() >= 2 && seen.insert(token.clone()) {
            tokens.push(token);
        }
    }
    tokens
}

/// Most frequent `top_n` tokens of `text` (ties broken by first occurrence).
fn top_tokens(text: &str, top_n: usize) -> HashSet<String> {
    // token -> (occurrence count, first-seen position)
    let mut counts: HashMap<String, (usize, usize)> = HashMap::new();
    let mut position = 0usize;
    for raw in text.split(|c: char| !c.is_alphanumeric()) {
        let token = raw.to_lowercase();
        if token.chars().count() < 2 {
            continue;
        }
        let slot = counts.entry(token).or_insert((0, position));
        slot.0 += 1;
        position += 1;
    }
    let mut ranked: Vec<(usize, usize, String)> = counts
        .into_iter()
        .map(|(token, (count, first_seen))| (count, first_seen, token))
        .collect();
    ranked.sort_by(|a, b| b.0.cmp(&a.0).then_with(|| a.1.cmp(&b.1)));
    ranked
        .into_iter()
        .take(top_n)
        .map(|(_, _, token)| token)
        .collect()
}

/// Naive entity extraction: capitalized words (length ≥ 3), lowercased.
fn extract_entities(text: &str) -> HashSet<String> {
    text.split(|c: char| !c.is_alphanumeric())
        .filter(|w| w.chars().count() >= 3)
        .filter(|w| w.chars().next().is_some_and(char::is_uppercase))
        .map(str::to_lowercase)
        .collect()
}

fn jaccard(a: &HashSet<String>, b: &HashSet<String>) -> f64 {
    if a.is_empty() || b.is_empty() {
        return 0.0;
    }
    let intersection = a.intersection(b).count();
    let union = a.len() + b.len() - intersection;
    if union == 0 {
        return 0.0;
    }
    #[allow(clippy::cast_precision_loss)]
    {
        intersection as f64 / union as f64
    }
}

/// H-MEM layer weight: long_term 1.0, working 0.8, short_term 0.6.
fn layer_weight(category: &MemoryCategory) -> f64 {
    match category {
        MemoryCategory::Core => 1.0,
        MemoryCategory::Daily | MemoryCategory::Custom(_) => 0.8,
        MemoryCategory::Conversation => 0.6,
    }
}

/// Exponential recency decay over a ~14-day constant. Unparseable
/// timestamps score a neutral 0.5 so legacy rows are not zeroed out.
fn recency_signal(timestamp: &str, now: DateTime<Utc>) -> f64 {
    let Ok(parsed) = DateTime::parse_from_rfc3339(timestamp) else {
        return 0.5;
    };
    let age_secs = (now - parsed.with_timezone(&Utc)).num_seconds().max(0);
    #[allow(clippy::cast_precision_loss)]
    let age_days = age_secs as f64 / 86_400.0;
    (-age_days / RECENCY_DECAY_DAYS).exp().clamp(0.0, 1.0)
}

/// Domain alignment via namespace: an explicit namespace mentioned in the
/// query scores 1.0, the catch-all `default` namespace scores a neutral
/// 0.5, and a non-matching explicit namespace scores 0.0.
fn domain_signal(namespace: &str, query_tokens: &HashSet<String>) -> f64 {
    if namespace == "default" {
        return 0.5;
    }
    if tokenize(namespace)
        .iter()
        .any(|token| query_tokens.contains(token))
    {
        1.0
    } else {
        0.0
    }
}

/// Precomputed query-side signals, shared across all candidates.
struct QuerySignals {
    tokens: HashSet<String>,
    top_tokens: HashSet<String>,
    entities: HashSet<String>,
}

impl QuerySignals {
    fn from_query(query: &str) -> Self {
        Self {
            tokens: tokenize(query).into_iter().collect(),
            top_tokens: top_tokens(query, KEYWORD_TOP_TOKENS),
            entities: extract_entities(query),
        }
    }
}

/// Final H-MEM score for one candidate. `semantic` is the inner hybrid
/// score max-normalized across the candidate pool.
fn score_entry(
    query: &QuerySignals,
    entry: &MemoryEntry,
    semantic: f64,
    now: DateTime<Utc>,
) -> f64 {
    let keyword = jaccard(
        &query.top_tokens,
        &top_tokens(&entry.content, KEYWORD_TOP_TOKENS),
    );
    // Keys act as tags in R.A.I.N.; "direct match weight" per spec.
    let key_tokens: HashSet<String> = tokenize(&entry.key).into_iter().collect();
    let tag = if key_tokens.is_disjoint(&query.tokens) {
        0.0
    } else {
        1.0
    };
    let domain = domain_signal(&entry.namespace, &query.tokens);
    let entity = {
        let entry_entities = extract_entities(&entry.content);
        if query.entities.is_empty() {
            0.0
        } else {
            #[allow(clippy::cast_precision_loss)]
            {
                query.entities.intersection(&entry_entities).count() as f64
                    / query.entities.len() as f64
            }
        }
    };
    let layer = layer_weight(&entry.category);
    let recency = recency_signal(&entry.timestamp, now);
    let superseded = if entry.superseded_by.is_some() {
        1.0
    } else {
        0.0
    };

    let raw = W_SEMANTIC * semantic
        + W_KEYWORD * keyword
        + W_TAG * tag
        + W_DOMAIN * domain
        + W_ENTITY * entity
        + W_LAYER * layer
        + W_RECENCY * recency
        - SUPERSEDED_PENALTY * superseded;

    let confidence = entry.importance.unwrap_or(1.0).clamp(0.0, 1.0);
    raw.clamp(0.0, 1.0) * confidence
}

/// Re-rank a candidate pool with the H-MEM formula, threshold at 0.35,
/// and keep the top `limit`. Scores are written back onto the entries.
fn rank_entries(
    query: &str,
    pool: Vec<MemoryEntry>,
    limit: usize,
    now: DateTime<Utc>,
) -> Vec<MemoryEntry> {
    if limit == 0 || pool.is_empty() {
        return Vec::new();
    }
    let signals = QuerySignals::from_query(query);

    // Max-normalize inner hybrid scores across the pool (same approach as
    // BM25 normalization in `vector::hybrid_merge`).
    let max_inner = pool.iter().filter_map(|e| e.score).fold(0.0_f64, f64::max);

    let mut scored: Vec<MemoryEntry> = pool
        .into_iter()
        .map(|mut entry| {
            let semantic = if max_inner > f64::EPSILON {
                (entry.score.unwrap_or(0.0) / max_inner).clamp(0.0, 1.0)
            } else {
                0.0
            };
            let final_score = score_entry(&signals, &entry, semantic, now);
            entry.score = Some(final_score);
            entry
        })
        .filter(|entry| entry.score.unwrap_or(0.0) >= SCORE_THRESHOLD)
        .collect();

    scored.sort_by(|a, b| {
        b.score
            .unwrap_or(0.0)
            .partial_cmp(&a.score.unwrap_or(0.0))
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    scored.truncate(limit);
    scored
}

#[async_trait]
impl Memory for HmemMemory {
    fn name(&self) -> &str {
        "hmem"
    }

    async fn store(
        &self,
        key: &str,
        content: &str,
        category: MemoryCategory,
        session_id: Option<&str>,
    ) -> anyhow::Result<()> {
        if content.trim().is_empty() {
            anyhow::bail!("hmem rejects empty memory content (provenance requires substance)");
        }
        self.inner
            .store(key, content, category.clone(), session_id)
            .await?;
        self.record_store(key, content, &category, session_id, None)
    }

    async fn store_with_metadata(
        &self,
        key: &str,
        content: &str,
        category: MemoryCategory,
        session_id: Option<&str>,
        namespace: Option<&str>,
        importance: Option<f64>,
    ) -> anyhow::Result<()> {
        if content.trim().is_empty() {
            anyhow::bail!("hmem rejects empty memory content (provenance requires substance)");
        }
        self.inner
            .store_with_metadata(
                key,
                content,
                category.clone(),
                session_id,
                namespace,
                importance,
            )
            .await?;
        self.record_store(key, content, &category, session_id, namespace)
    }

    async fn recall(
        &self,
        query: &str,
        limit: usize,
        session_id: Option<&str>,
        since: Option<&str>,
        until: Option<&str>,
    ) -> anyhow::Result<Vec<MemoryEntry>> {
        if limit == 0 {
            return Ok(Vec::new());
        }
        let pool = self
            .inner
            .recall(query, Self::pool_limit(limit), session_id, since, until)
            .await?;
        Ok(rank_entries(query, pool, limit, Utc::now()))
    }

    async fn recall_namespaced(
        &self,
        namespace: &str,
        query: &str,
        limit: usize,
        session_id: Option<&str>,
        since: Option<&str>,
        until: Option<&str>,
    ) -> anyhow::Result<Vec<MemoryEntry>> {
        if limit == 0 {
            return Ok(Vec::new());
        }
        let pool = self
            .inner
            .recall_namespaced(
                namespace,
                query,
                Self::pool_limit(limit),
                session_id,
                since,
                until,
            )
            .await?;
        Ok(rank_entries(query, pool, limit, Utc::now()))
    }

    async fn get(&self, key: &str) -> anyhow::Result<Option<MemoryEntry>> {
        self.inner.get(key).await
    }

    async fn list(
        &self,
        category: Option<&MemoryCategory>,
        session_id: Option<&str>,
    ) -> anyhow::Result<Vec<MemoryEntry>> {
        self.inner.list(category, session_id).await
    }

    async fn forget(&self, key: &str) -> anyhow::Result<bool> {
        let removed = self.inner.forget(key).await?;
        if removed {
            self.append_ledger(&TrustLedgerRecord {
                ts: Utc::now().to_rfc3339(),
                action: "forget".to_string(),
                key: key.to_string(),
                source: "direct".to_string(),
                category: None,
                namespace: None,
                session_id: None,
                content_sha256: None,
                affected: None,
            })?;
        }
        Ok(removed)
    }

    async fn purge_namespace(&self, namespace: &str) -> anyhow::Result<usize> {
        let affected = self.inner.purge_namespace(namespace).await?;
        self.append_ledger(&TrustLedgerRecord {
            ts: Utc::now().to_rfc3339(),
            action: "purge_namespace".to_string(),
            key: "*".to_string(),
            source: "direct".to_string(),
            category: None,
            namespace: Some(namespace.to_string()),
            session_id: None,
            content_sha256: None,
            affected: Some(affected),
        })?;
        Ok(affected)
    }

    async fn purge_session(&self, session_id: &str) -> anyhow::Result<usize> {
        let affected = self.inner.purge_session(session_id).await?;
        self.append_ledger(&TrustLedgerRecord {
            ts: Utc::now().to_rfc3339(),
            action: "purge_session".to_string(),
            key: "*".to_string(),
            source: Self::derive_source(Some(session_id)),
            category: None,
            namespace: None,
            session_id: Some(session_id.to_string()),
            content_sha256: None,
            affected: Some(affected),
        })?;
        Ok(affected)
    }

    async fn count(&self) -> anyhow::Result<usize> {
        self.inner.count().await
    }

    async fn health_check(&self) -> bool {
        self.inner.health_check().await
    }

    async fn store_procedural(
        &self,
        messages: &[ProceduralMessage],
        session_id: Option<&str>,
    ) -> anyhow::Result<()> {
        // Inner sqlite backend does not persist procedural traces; delegate
        // without a ledger record because no mutation occurs.
        self.inner.store_procedural(messages, session_id).await
    }

    async fn export(&self, filter: &ExportFilter) -> anyhow::Result<Vec<MemoryEntry>> {
        self.inner.export(filter).await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn make_entry(key: &str, content: &str, category: MemoryCategory) -> MemoryEntry {
        MemoryEntry {
            id: format!("id-{key}"),
            key: key.to_string(),
            content: content.to_string(),
            category,
            timestamp: Utc::now().to_rfc3339(),
            session_id: None,
            score: Some(1.0),
            namespace: "default".to_string(),
            importance: None,
            superseded_by: None,
        }
    }

    fn score_of(query: &str, entry: &MemoryEntry) -> f64 {
        let signals = QuerySignals::from_query(query);
        score_entry(&signals, entry, 1.0, Utc::now())
    }

    fn build_hmem(tmp: &TempDir) -> HmemMemory {
        let inner = SqliteMemory::new(tmp.path()).expect("sqlite init");
        HmemMemory::new(tmp.path(), inner)
    }

    #[test]
    fn superseded_entries_score_lower_than_active_ones() {
        let active = make_entry(
            "rust_style",
            "Prefer explicit match arms in Rust",
            MemoryCategory::Core,
        );
        let mut superseded = active.clone();
        superseded.superseded_by = Some("rust_style_v2".to_string());

        let query = "explicit match arms rust";
        assert!(score_of(query, &active) > score_of(query, &superseded));
    }

    #[test]
    fn layer_weights_rank_core_above_conversation() {
        let core = make_entry("fact", "deployment target is metal", MemoryCategory::Core);
        let mut conversation = core.clone();
        conversation.category = MemoryCategory::Conversation;

        let query = "deployment target metal";
        assert!(score_of(query, &core) > score_of(query, &conversation));
        assert_eq!(layer_weight(&MemoryCategory::Core), 1.0);
        assert_eq!(layer_weight(&MemoryCategory::Conversation), 0.6);
        assert_eq!(layer_weight(&MemoryCategory::Daily), 0.8);
    }

    #[test]
    fn recency_signal_decays_with_age() {
        let now = Utc::now();
        let fresh = now.to_rfc3339();
        let stale = (now - chrono::Duration::days(60)).to_rfc3339();

        let fresh_signal = recency_signal(&fresh, now);
        let stale_signal = recency_signal(&stale, now);
        assert!(fresh_signal > 0.9);
        assert!(stale_signal < 0.05);
        assert!(fresh_signal > stale_signal);
        // Unparseable timestamps stay neutral instead of zeroing out.
        assert!((recency_signal("not-a-date", now) - 0.5).abs() < f64::EPSILON);
    }

    #[test]
    fn rank_entries_filters_below_threshold_and_orders_by_score() {
        let now = Utc::now();
        let strong = make_entry(
            "language_preference",
            "The user prefers the Rust language for systems work",
            MemoryCategory::Core,
        );
        let mut weak = make_entry(
            "noise",
            "unrelated grocery list",
            MemoryCategory::Conversation,
        );
        weak.score = Some(0.05);
        weak.timestamp = (now - chrono::Duration::days(120)).to_rfc3339();

        let ranked = rank_entries(
            "language preference rust",
            vec![weak, strong.clone()],
            5,
            now,
        );
        assert_eq!(ranked.len(), 1, "weak candidate must fall below 0.35");
        assert_eq!(ranked[0].key, strong.key);
        assert!(ranked[0].score.unwrap_or(0.0) >= SCORE_THRESHOLD);
    }

    #[test]
    fn rank_entries_respects_limit_and_zero_limit() {
        let now = Utc::now();
        let pool: Vec<MemoryEntry> = (0..6)
            .map(|i| {
                make_entry(
                    &format!("rust_fact_{i}"),
                    "rust ownership and borrowing rules",
                    MemoryCategory::Core,
                )
            })
            .collect();

        assert_eq!(
            rank_entries("rust ownership", pool.clone(), 3, now).len(),
            3
        );
        assert!(rank_entries("rust ownership", pool, 0, now).is_empty());
    }

    #[test]
    fn domain_signal_matches_namespace_against_query() {
        let query_tokens: HashSet<String> =
            tokenize("deploy the robotics stack").into_iter().collect();
        assert!((domain_signal("robotics", &query_tokens) - 1.0).abs() < f64::EPSILON);
        assert!((domain_signal("default", &query_tokens) - 0.5).abs() < f64::EPSILON);
        assert!((domain_signal("finance", &query_tokens)).abs() < f64::EPSILON);
    }

    #[test]
    fn confidence_scales_final_score() {
        let full = make_entry(
            "pref",
            "user prefers dark mode themes",
            MemoryCategory::Core,
        );
        let mut low_confidence = full.clone();
        low_confidence.importance = Some(0.5);

        let query = "dark mode preference";
        let full_score = score_of(query, &full);
        let scaled = score_of(query, &low_confidence);
        assert!((scaled - full_score * 0.5).abs() < 1e-9);
    }

    #[tokio::test]
    async fn store_and_recall_roundtrip_with_hmem_scores() {
        let tmp = TempDir::new().unwrap();
        let mem = build_hmem(&tmp);
        assert_eq!(mem.name(), "hmem");

        mem.store(
            "favorite_language",
            "The user's favorite language is Rust",
            MemoryCategory::Core,
            None,
        )
        .await
        .unwrap();

        let results = mem
            .recall("favorite language rust", 5, None, None, None)
            .await
            .unwrap();
        assert_eq!(results.len(), 1);
        assert_eq!(results[0].key, "favorite_language");
        let score = results[0].score.expect("hmem score present");
        assert!((SCORE_THRESHOLD..=1.0).contains(&score));
    }

    #[tokio::test]
    async fn store_rejects_empty_content() {
        let tmp = TempDir::new().unwrap();
        let mem = build_hmem(&tmp);

        let err = mem
            .store("empty", "   ", MemoryCategory::Core, None)
            .await
            .expect_err("empty content must be rejected");
        assert!(err.to_string().contains("empty memory content"));
        assert_eq!(mem.count().await.unwrap(), 0);
    }

    #[tokio::test]
    async fn mutations_append_to_trust_ledger_without_raw_content() {
        let tmp = TempDir::new().unwrap();
        let mem = build_hmem(&tmp);
        let secret_content = "api endpoint rotation happens on Tuesdays";

        mem.store(
            "ops_note",
            secret_content,
            MemoryCategory::Daily,
            Some("session-1"),
        )
        .await
        .unwrap();
        mem.forget("ops_note").await.unwrap();

        let raw = std::fs::read_to_string(mem.ledger_path()).unwrap();
        let lines: Vec<&str> = raw.lines().collect();
        assert_eq!(lines.len(), 2, "one record per mutation");

        let store_rec: TrustLedgerRecord = serde_json::from_str(lines[0]).unwrap();
        assert_eq!(store_rec.action, "store");
        assert_eq!(store_rec.key, "ops_note");
        assert_eq!(store_rec.source, "session:session-1");
        assert_eq!(
            store_rec.content_sha256.as_deref(),
            Some(HmemMemory::content_digest(secret_content).as_str())
        );
        assert!(
            !raw.contains(secret_content),
            "ledger must never contain raw content"
        );

        let forget_rec: TrustLedgerRecord = serde_json::from_str(lines[1]).unwrap();
        assert_eq!(forget_rec.action, "forget");
        assert_eq!(forget_rec.key, "ops_note");
    }

    #[tokio::test]
    async fn forget_missing_key_leaves_ledger_untouched() {
        let tmp = TempDir::new().unwrap();
        let mem = build_hmem(&tmp);

        let removed = mem.forget("never_stored").await.unwrap();
        assert!(!removed);
        assert!(
            !mem.ledger_path().exists(),
            "no mutation happened, so no ledger record"
        );
    }

    #[test]
    fn tokenize_dedupes_and_lowercases() {
        let tokens = tokenize("Rust rust RUST memory! memory");
        assert_eq!(tokens, vec!["rust".to_string(), "memory".to_string()]);
    }

    #[test]
    fn entity_extraction_uses_capitalized_words() {
        let entities = extract_entities("Deploy Meterless on the Jetson board");
        assert!(entities.contains("meterless"));
        assert!(entities.contains("jetson"));
        assert!(entities.contains("deploy"));
        assert!(!entities.contains("board"));
    }
}
