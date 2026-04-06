use super::embeddings::EmbeddingProvider;
use super::traits::{Memory, MemoryCategory, MemoryEntry};
use super::vector;
use async_trait::async_trait;
use chrono::Local;
use parking_lot::Mutex;
use rusqlite::{Connection, params};
use std::fmt::Write as _;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use uuid::Uuid;

const DEFAULT_FIELD_ENERGY: f64 = 1.0;
const DEFAULT_RESONANCE_THRESHOLD: f64 = 0.85;
const DEFAULT_MASS_TOKENS_PER_UNIT: f64 = 128.0;

#[derive(Debug, Clone)]
pub struct ResonantObject {
    pub entry: MemoryEntry,
    pub intrinsic_frequency: Vec<f32>,
    pub mass_equivalent: f64,
}

#[derive(Debug, Clone)]
pub struct ScalarField {
    pub current_frequency: Vec<f32>,
    pub field_energy: f64,
}

impl Default for ScalarField {
    fn default() -> Self {
        Self {
            current_frequency: Vec::new(),
            field_energy: DEFAULT_FIELD_ENERGY,
        }
    }
}

impl ScalarField {
    pub fn calculate_resonance(&self, object: &ResonantObject) -> f64 {
        let overlap = f64::from(vector::cosine_similarity(
            &self.current_frequency,
            &object.intrinsic_frequency,
        ));
        let denom = self.field_energy * object.mass_equivalent;
        if !denom.is_finite() || denom <= f64::EPSILON {
            return 0.0;
        }
        let coupling = overlap / denom;
        if coupling.is_finite() { coupling } else { 0.0 }
    }
}

#[derive(Clone, Default)]
struct RecallFilters {
    session_id: Option<String>,
    since: Option<String>,
    until: Option<String>,
}

pub struct ResonanceMemory {
    conn: Arc<Mutex<Connection>>,
    _db_path: PathBuf,
    embedder: Arc<dyn EmbeddingProvider>,
    field_energy: f64,
    resonance_threshold: f64,
    mass_tokens_per_unit: f64,
}

/// Backward-compatible alias for older call sites.
pub type ResonanceBackend = ResonanceMemory;

impl ResonanceMemory {
    pub fn with_embedder(
        workspace_dir: &Path,
        embedder: Arc<dyn EmbeddingProvider>,
    ) -> anyhow::Result<Self> {
        Self::with_embedder_and_params(
            workspace_dir,
            embedder,
            DEFAULT_RESONANCE_THRESHOLD,
            DEFAULT_FIELD_ENERGY,
            DEFAULT_MASS_TOKENS_PER_UNIT,
        )
    }

    pub fn with_embedder_and_params(
        workspace_dir: &Path,
        embedder: Arc<dyn EmbeddingProvider>,
        resonance_threshold: f64,
        field_energy: f64,
        mass_tokens_per_unit: f64,
    ) -> anyhow::Result<Self> {
        let db_path = workspace_dir.join("memory").join("resonance.db");
        if let Some(parent) = db_path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let conn = Connection::open(&db_path)?;
        Self::init_schema(&conn)?;
        Ok(Self {
            conn: Arc::new(Mutex::new(conn)),
            _db_path: db_path,
            embedder,
            field_energy: if field_energy.is_finite() && field_energy > f64::EPSILON {
                field_energy
            } else {
                DEFAULT_FIELD_ENERGY
            },
            resonance_threshold: if resonance_threshold.is_finite() {
                resonance_threshold
            } else {
                DEFAULT_RESONANCE_THRESHOLD
            },
            mass_tokens_per_unit: if mass_tokens_per_unit.is_finite()
                && mass_tokens_per_unit > f64::EPSILON
            {
                mass_tokens_per_unit
            } else {
                DEFAULT_MASS_TOKENS_PER_UNIT
            },
        })
    }

    fn init_schema(conn: &Connection) -> anyhow::Result<()> {
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS resonance_memories (
                id              TEXT PRIMARY KEY,
                key             TEXT NOT NULL UNIQUE,
                content         TEXT NOT NULL,
                category        TEXT NOT NULL DEFAULT 'core',
                intrinsic_freq  BLOB,
                mass_equivalent REAL NOT NULL DEFAULT 1.0,
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL,
                session_id      TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_res_mem_key ON resonance_memories(key);
            CREATE INDEX IF NOT EXISTS idx_res_mem_session ON resonance_memories(session_id);
            CREATE INDEX IF NOT EXISTS idx_res_mem_created ON resonance_memories(created_at);",
        )?;
        Ok(())
    }

    fn category_to_str(cat: &MemoryCategory) -> String {
        match cat {
            MemoryCategory::Core => "core".into(),
            MemoryCategory::Daily => "daily".into(),
            MemoryCategory::Conversation => "conversation".into(),
            MemoryCategory::Custom(name) => name.clone(),
        }
    }

    fn str_to_category(s: &str) -> MemoryCategory {
        match s {
            "core" => MemoryCategory::Core,
            "daily" => MemoryCategory::Daily,
            "conversation" => MemoryCategory::Conversation,
            other => MemoryCategory::Custom(other.to_string()),
        }
    }

    fn estimate_mass_equivalent(content: &str, mass_tokens_per_unit: f64) -> f64 {
        let approx_tokens = content.split_whitespace().count().max(1) as f64;
        let denom = if mass_tokens_per_unit.is_finite() && mass_tokens_per_unit > f64::EPSILON {
            mass_tokens_per_unit
        } else {
            DEFAULT_MASS_TOKENS_PER_UNIT
        };
        (approx_tokens / denom).max(1.0)
    }

    async fn compute_embedding(&self, text: &str) -> anyhow::Result<Option<Vec<f32>>> {
        if self.embedder.dimensions() == 0 {
            return Ok(None);
        }
        Ok(Some(self.embedder.embed_one(text).await?))
    }

    fn push_recall_filters(
        sql: &mut String,
        param_values: &mut Vec<Box<dyn rusqlite::types::ToSql>>,
        idx: &mut usize,
        filters: &RecallFilters,
    ) {
        if let Some(sid) = filters.session_id.as_deref() {
            let _ = write!(sql, " AND session_id = ?{idx}");
            param_values.push(Box::new(sid.to_string()));
            *idx += 1;
        }
        if let Some(since) = filters.since.as_deref() {
            let _ = write!(sql, " AND created_at >= ?{idx}");
            param_values.push(Box::new(since.to_string()));
            *idx += 1;
        }
        if let Some(until) = filters.until.as_deref() {
            let _ = write!(sql, " AND created_at <= ?{idx}");
            param_values.push(Box::new(until.to_string()));
            *idx += 1;
        }
    }

    fn load_resonant_objects(
        conn: &Connection,
        filters: &RecallFilters,
    ) -> anyhow::Result<Vec<ResonantObject>> {
        let mut sql = "SELECT id, key, content, category, created_at, session_id, intrinsic_freq, mass_equivalent
                       FROM resonance_memories WHERE intrinsic_freq IS NOT NULL"
            .to_string();
        let mut param_values: Vec<Box<dyn rusqlite::types::ToSql>> = Vec::new();
        let mut idx = 1;
        Self::push_recall_filters(&mut sql, &mut param_values, &mut idx, filters);
        sql.push_str(" ORDER BY updated_at DESC");

        let mut stmt = conn.prepare(&sql)?;
        let params_ref: Vec<&dyn rusqlite::types::ToSql> =
            param_values.iter().map(AsRef::as_ref).collect();
        let rows = stmt.query_map(params_ref.as_slice(), |row| {
            let id: String = row.get(0)?;
            let key: String = row.get(1)?;
            let content: String = row.get(2)?;
            let category: String = row.get(3)?;
            let timestamp: String = row.get(4)?;
            let session_id: Option<String> = row.get(5)?;
            let embedding_blob: Vec<u8> = row.get(6)?;
            let mass_equivalent: f64 = row.get(7)?;

            Ok(ResonantObject {
                entry: MemoryEntry {
                    id,
                    key,
                    content,
                    category: Self::str_to_category(&category),
                    timestamp,
                    session_id,
                    score: None,
                    namespace: "default".into(),
                    importance: None,
                    superseded_by: None,
                },
                intrinsic_frequency: vector::bytes_to_vec(&embedding_blob),
                mass_equivalent,
            })
        })?;

        let mut objects = Vec::new();
        for row in rows {
            objects.push(row?);
        }
        Ok(objects)
    }

    async fn tune_and_materialize(
        &self,
        target_frequency: Vec<f32>,
        filters: RecallFilters,
        limit: usize,
    ) -> anyhow::Result<Vec<MemoryEntry>> {
        let field = ScalarField {
            current_frequency: target_frequency,
            field_energy: if self.field_energy.is_finite() && self.field_energy > f64::EPSILON {
                self.field_energy
            } else {
                DEFAULT_FIELD_ENERGY
            },
        };

        let conn = self.conn.clone();
        let objects =
            tokio::task::spawn_blocking(move || -> anyhow::Result<Vec<ResonantObject>> {
                let conn = conn.lock();
                Self::load_resonant_objects(&conn, &filters)
            })
            .await??;

        let mut coupled: Vec<(MemoryEntry, f64)> = objects
            .into_iter()
            .filter_map(|object| {
                let coupling = field.calculate_resonance(&object);
                (coupling > self.resonance_threshold).then(|| {
                    let mut entry = object.entry;
                    entry.score = Some(coupling);
                    (entry, coupling)
                })
            })
            .collect();

        coupled.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
        coupled.truncate(limit);
        Ok(coupled.into_iter().map(|(entry, _)| entry).collect())
    }
}

#[async_trait]
impl Memory for ResonanceMemory {
    fn name(&self) -> &str {
        "resonance"
    }

    async fn store(
        &self,
        key: &str,
        content: &str,
        category: MemoryCategory,
        session_id: Option<&str>,
    ) -> anyhow::Result<()> {
        let intrinsic_frequency = self.compute_embedding(content).await?;
        let mass_equivalent = Self::estimate_mass_equivalent(content, self.mass_tokens_per_unit);
        let embedding_bytes = intrinsic_frequency.as_deref().map(vector::vec_to_bytes);

        let conn = self.conn.clone();
        let key = key.to_string();
        let content = content.to_string();
        let sid = session_id.map(String::from);
        tokio::task::spawn_blocking(move || -> anyhow::Result<()> {
            let conn = conn.lock();
            let now = Local::now().to_rfc3339();
            let id = Uuid::new_v4().to_string();
            let cat = Self::category_to_str(&category);

            conn.execute(
                "INSERT INTO resonance_memories
                 (id, key, content, category, intrinsic_freq, mass_equivalent, created_at, updated_at, session_id)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)
                 ON CONFLICT(key) DO UPDATE SET
                    content = excluded.content,
                    category = excluded.category,
                    intrinsic_freq = excluded.intrinsic_freq,
                    mass_equivalent = excluded.mass_equivalent,
                    updated_at = excluded.updated_at,
                    session_id = excluded.session_id",
                params![
                    id,
                    key,
                    content,
                    cat,
                    embedding_bytes,
                    mass_equivalent,
                    now,
                    now,
                    sid
                ],
            )?;
            Ok(())
        })
        .await?
    }

    async fn recall(
        &self,
        query: &str,
        limit: usize,
        session_id: Option<&str>,
        since: Option<&str>,
        until: Option<&str>,
    ) -> anyhow::Result<Vec<MemoryEntry>> {
        if query.trim().is_empty() {
            return self.list(None, session_id).await.map(|entries| {
                let mut filtered: Vec<_> = entries
                    .into_iter()
                    .filter(|entry| {
                        let after_since = since.is_none_or(|s| entry.timestamp.as_str() >= s);
                        let before_until = until.is_none_or(|u| entry.timestamp.as_str() <= u);
                        after_since && before_until
                    })
                    .collect();
                filtered.truncate(limit);
                filtered
            });
        }

        let Some(target_frequency) = self.compute_embedding(query).await? else {
            return Ok(Vec::new());
        };

        self.tune_and_materialize(
            target_frequency,
            RecallFilters {
                session_id: session_id.map(ToString::to_string),
                since: since.map(ToString::to_string),
                until: until.map(ToString::to_string),
            },
            limit,
        )
        .await
    }

    async fn get(&self, key: &str) -> anyhow::Result<Option<MemoryEntry>> {
        let conn = self.conn.clone();
        let key = key.to_string();
        tokio::task::spawn_blocking(move || -> anyhow::Result<Option<MemoryEntry>> {
            let conn = conn.lock();
            let mut stmt = conn.prepare(
                "SELECT id, key, content, category, created_at, session_id
                 FROM resonance_memories WHERE key = ?1",
            )?;
            let mut rows = stmt.query_map(params![key], |row| {
                Ok(MemoryEntry {
                    id: row.get(0)?,
                    key: row.get(1)?,
                    content: row.get(2)?,
                    category: Self::str_to_category(&row.get::<_, String>(3)?),
                    timestamp: row.get(4)?,
                    session_id: row.get(5)?,
                    score: None,
                    namespace: "default".into(),
                    importance: None,
                    superseded_by: None,
                })
            })?;
            match rows.next() {
                Some(Ok(entry)) => Ok(Some(entry)),
                _ => Ok(None),
            }
        })
        .await?
    }

    async fn list(
        &self,
        category: Option<&MemoryCategory>,
        session_id: Option<&str>,
    ) -> anyhow::Result<Vec<MemoryEntry>> {
        let conn = self.conn.clone();
        let cat = category.cloned();
        let sid = session_id.map(String::from);
        tokio::task::spawn_blocking(move || -> anyhow::Result<Vec<MemoryEntry>> {
            let conn = conn.lock();
            let mut sql = "SELECT id, key, content, category, created_at, session_id
                           FROM resonance_memories WHERE 1=1"
                .to_string();
            let mut param_values: Vec<Box<dyn rusqlite::types::ToSql>> = Vec::new();
            let mut idx = 1;
            if let Some(cat) = cat.as_ref() {
                let _ = write!(sql, " AND category = ?{idx}");
                param_values.push(Box::new(Self::category_to_str(cat)));
                idx += 1;
            }
            if let Some(sid) = sid.as_deref() {
                let _ = write!(sql, " AND session_id = ?{idx}");
                param_values.push(Box::new(sid.to_string()));
            }
            sql.push_str(" ORDER BY updated_at DESC");

            let mut stmt = conn.prepare(&sql)?;
            let params_ref: Vec<&dyn rusqlite::types::ToSql> =
                param_values.iter().map(AsRef::as_ref).collect();
            let rows = stmt.query_map(params_ref.as_slice(), |row| {
                Ok(MemoryEntry {
                    id: row.get(0)?,
                    key: row.get(1)?,
                    content: row.get(2)?,
                    category: Self::str_to_category(&row.get::<_, String>(3)?),
                    timestamp: row.get(4)?,
                    session_id: row.get(5)?,
                    score: None,
                    namespace: "default".into(),
                    importance: None,
                    superseded_by: None,
                })
            })?;

            let mut entries = Vec::new();
            for row in rows {
                entries.push(row?);
            }
            Ok(entries)
        })
        .await?
    }

    async fn forget(&self, key: &str) -> anyhow::Result<bool> {
        let conn = self.conn.clone();
        let key = key.to_string();
        tokio::task::spawn_blocking(move || -> anyhow::Result<bool> {
            let conn = conn.lock();
            let affected = conn.execute(
                "DELETE FROM resonance_memories WHERE key = ?1",
                params![key],
            )?;
            Ok(affected > 0)
        })
        .await?
    }

    async fn count(&self) -> anyhow::Result<usize> {
        let conn = self.conn.clone();
        tokio::task::spawn_blocking(move || -> anyhow::Result<usize> {
            let conn = conn.lock();
            let count: i64 =
                conn.query_row("SELECT COUNT(*) FROM resonance_memories", [], |row| {
                    row.get(0)
                })?;
            #[allow(clippy::cast_sign_loss, clippy::cast_possible_truncation)]
            Ok(count as usize)
        })
        .await?
    }

    async fn health_check(&self) -> bool {
        let conn = self.conn.clone();
        tokio::task::spawn_blocking(move || conn.lock().execute_batch("SELECT 1").is_ok())
            .await
            .unwrap_or(false)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use async_trait::async_trait;
    use tempfile::TempDir;

    struct TestEmbedding;

    #[async_trait]
    impl EmbeddingProvider for TestEmbedding {
        fn name(&self) -> &str {
            "test"
        }

        fn dimensions(&self) -> usize {
            3
        }

        async fn embed(&self, texts: &[&str]) -> anyhow::Result<Vec<Vec<f32>>> {
            Ok(texts
                .iter()
                .map(|text| {
                    if text.to_ascii_lowercase().contains("rust") {
                        vec![1.0, 0.0, 0.0]
                    } else {
                        vec![0.0, 1.0, 0.0]
                    }
                })
                .collect())
        }
    }

    fn temp_backend() -> (TempDir, ResonanceBackend) {
        let tmp = TempDir::new().unwrap();
        let backend = ResonanceBackend::with_embedder_and_params(
            tmp.path(),
            Arc::new(TestEmbedding),
            DEFAULT_RESONANCE_THRESHOLD,
            DEFAULT_FIELD_ENERGY,
            DEFAULT_MASS_TOKENS_PER_UNIT,
        )
        .unwrap();
        (tmp, backend)
    }

    #[tokio::test]
    async fn resonance_store_and_recall_filters_by_threshold() {
        let (_tmp, backend) = temp_backend();
        backend
            .store("k1", "Rust memory", MemoryCategory::Core, None)
            .await
            .unwrap();
        backend
            .store("k2", "Python memory", MemoryCategory::Core, None)
            .await
            .unwrap();

        let results = backend.recall("Rust", 1, None, None, None).await.unwrap();
        assert_eq!(results.len(), 1);
        assert_eq!(results[0].key, "k1");
        assert!(results[0].score.unwrap_or_default() > DEFAULT_RESONANCE_THRESHOLD);
    }

    #[tokio::test]
    async fn resonance_supports_trait_ops() {
        let (_tmp, backend) = temp_backend();
        backend
            .store("k1", "Rust memory", MemoryCategory::Core, Some("s1"))
            .await
            .unwrap();
        assert_eq!(backend.count().await.unwrap(), 1);
        assert!(backend.get("k1").await.unwrap().is_some());
        assert_eq!(backend.list(None, Some("s1")).await.unwrap().len(), 1);
        assert!(backend.forget("k1").await.unwrap());
        assert_eq!(backend.count().await.unwrap(), 0);
    }
}
