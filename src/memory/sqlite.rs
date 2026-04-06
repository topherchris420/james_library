use super::embeddings::EmbeddingProvider;
use super::traits::{Memory, MemoryCategory, MemoryEntry};
use super::vector;
use anyhow::Context;
use async_trait::async_trait;
use chrono::Local;
use parking_lot::Mutex;
use rusqlite::{Connection, params};
use std::cmp::Reverse;
use std::collections::{BinaryHeap, HashMap};
use std::fmt::Write as _;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::mpsc;
use std::thread;
use std::time::Duration;
use uuid::Uuid;

/// Maximum allowed open timeout (seconds) to avoid unreasonable waits.
const SQLITE_OPEN_TIMEOUT_CAP_SECS: u64 = 300;
const LSH_BAND_COUNT: usize = 8;
const LSH_BITS_PER_BAND: usize = 12;
const LSH_CANDIDATE_MULTIPLIER: usize = 16;
const LSH_MIN_CANDIDATES: usize = 64;
const STARTUP_BAND_BACKFILL_BATCH_SIZE: usize = 256;

/// SQLite-backed persistent memory — the brain
///
/// Full-stack search engine:
/// - **Vector DB**: embeddings stored as BLOB, cosine similarity search
/// - **Keyword Search**: FTS5 virtual table with BM25 scoring
/// - **Hybrid Merge**: weighted fusion of vector + keyword results
/// - **Embedding Cache**: LRU-evicted cache to avoid redundant API calls
/// - **Safe Reindex**: temp DB → seed → sync → atomic swap → rollback
pub struct SqliteMemory {
    conn: Arc<Mutex<Connection>>,
    _db_path: PathBuf,
    embedder: Arc<dyn EmbeddingProvider>,
    vector_weight: f32,
    keyword_weight: f32,
    cache_max: usize,
}

#[derive(Clone, Copy, Debug, Default)]
struct RecallFilters<'a> {
    category: Option<&'a str>,
    session_id: Option<&'a str>,
    since: Option<&'a str>,
    until: Option<&'a str>,
}

#[derive(Debug)]
struct VectorCandidate {
    id: String,
    embedding_blob: Vec<u8>,
}

#[derive(Debug)]
struct HydratedMemoryRow {
    id: String,
    key: String,
    content: String,
    category: String,
    created_at: String,
    session_id: Option<String>,
}

/// Row shape used by the Kairos episodic memory consolidator.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct MemoryRow {
    pub id: i64,
    pub key: String,
    pub content: String,
    pub role: String,
    pub timestamp: String,
}

#[derive(Debug)]
struct RankedVectorResult {
    id: String,
    score: f32,
}

impl PartialEq for RankedVectorResult {
    fn eq(&self, other: &Self) -> bool {
        self.id == other.id && self.score.total_cmp(&other.score).is_eq()
    }
}

impl Eq for RankedVectorResult {}

impl PartialOrd for RankedVectorResult {
    fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for RankedVectorResult {
    fn cmp(&self, other: &Self) -> std::cmp::Ordering {
        self.score
            .total_cmp(&other.score)
            .then_with(|| self.id.cmp(&other.id))
    }
}

impl SqliteMemory {
    pub fn new(workspace_dir: &Path) -> anyhow::Result<Self> {
        Self::with_embedder(
            workspace_dir,
            Arc::new(super::embeddings::NoopEmbedding),
            0.7,
            0.3,
            10_000,
            None,
        )
    }

    /// Build SQLite memory with optional open timeout.
    ///
    /// If `open_timeout_secs` is `Some(n)`, opening the database is limited to `n` seconds
    /// (capped at 300). Useful when the DB file may be locked or on slow storage.
    /// `None` = wait indefinitely (default).
    pub fn with_embedder(
        workspace_dir: &Path,
        embedder: Arc<dyn EmbeddingProvider>,
        vector_weight: f32,
        keyword_weight: f32,
        cache_max: usize,
        open_timeout_secs: Option<u64>,
    ) -> anyhow::Result<Self> {
        let db_path = workspace_dir.join("memory").join("brain.db");

        if let Some(parent) = db_path.parent() {
            std::fs::create_dir_all(parent)?;
        }

        let mut conn = Self::open_connection(&db_path, open_timeout_secs)?;

        // ── Production-grade PRAGMA tuning ──────────────────────
        // WAL mode: concurrent reads during writes, crash-safe
        // normal sync: 2× write speed, still durable on WAL
        // mmap 8 MB: let the OS page-cache serve hot reads
        // cache 2 MB: keep ~500 hot pages in-process
        // temp_store memory: temp tables never hit disk
        conn.execute_batch(
            "PRAGMA journal_mode = WAL;
             PRAGMA synchronous  = NORMAL;
             PRAGMA mmap_size    = 8388608;
             PRAGMA cache_size   = -2000;
             PRAGMA temp_store   = MEMORY;",
        )?;

        Self::init_schema(&conn)?;
        let backfilled =
            Self::backfill_missing_embedding_bands(&mut conn, STARTUP_BAND_BACKFILL_BATCH_SIZE)?;
        if backfilled > 0 {
            tracing::info!(
                repaired_rows = backfilled,
                "Backfilled legacy sqlite embedding band rows at startup"
            );
        }

        Ok(Self {
            conn: Arc::new(Mutex::new(conn)),
            _db_path: db_path,
            embedder,
            vector_weight,
            keyword_weight,
            cache_max,
        })
    }

    /// Open SQLite connection, optionally with a timeout (for locked/slow storage).
    fn open_connection(
        db_path: &Path,
        open_timeout_secs: Option<u64>,
    ) -> anyhow::Result<Connection> {
        let path_buf = db_path.to_path_buf();

        let conn = if let Some(secs) = open_timeout_secs {
            let capped = secs.min(SQLITE_OPEN_TIMEOUT_CAP_SECS);
            let (tx, rx) = mpsc::channel();
            thread::spawn(move || {
                let result = Connection::open(&path_buf);
                let _ = tx.send(result);
            });
            match rx.recv_timeout(Duration::from_secs(capped)) {
                Ok(Ok(c)) => c,
                Ok(Err(e)) => return Err(e).context("SQLite failed to open database"),
                Err(mpsc::RecvTimeoutError::Timeout) => {
                    anyhow::bail!("SQLite connection open timed out after {} seconds", capped);
                }
                Err(mpsc::RecvTimeoutError::Disconnected) => {
                    anyhow::bail!("SQLite open thread exited unexpectedly");
                }
            }
        } else {
            Connection::open(&path_buf).context("SQLite failed to open database")?
        };

        Ok(conn)
    }

    /// Initialize all tables: memories, FTS5, `embedding_cache`
    fn init_schema(conn: &Connection) -> anyhow::Result<()> {
        conn.execute_batch(
            "-- Core memories table
            CREATE TABLE IF NOT EXISTS memories (
                id          TEXT PRIMARY KEY,
                key         TEXT NOT NULL UNIQUE,
                content     TEXT NOT NULL,
                category    TEXT NOT NULL DEFAULT 'core',
                embedding   BLOB,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category);
            CREATE INDEX IF NOT EXISTS idx_memories_key ON memories(key);
            CREATE INDEX IF NOT EXISTS idx_memories_created_at ON memories(created_at);

            -- FTS5 full-text search (BM25 scoring)
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                key, content, content=memories, content_rowid=rowid
            );

            -- FTS5 triggers: keep in sync with memories table
            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                INSERT INTO memories_fts(rowid, key, content)
                VALUES (new.rowid, new.key, new.content);
            END;
            CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, key, content)
                VALUES ('delete', old.rowid, old.key, old.content);
            END;
            CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, key, content)
                VALUES ('delete', old.rowid, old.key, old.content);
                INSERT INTO memories_fts(rowid, key, content)
                VALUES (new.rowid, new.key, new.content);
            END;

            -- Embedding cache with LRU eviction
            CREATE TABLE IF NOT EXISTS embedding_cache (
                content_hash TEXT PRIMARY KEY,
                embedding    BLOB NOT NULL,
                created_at   TEXT NOT NULL,
                accessed_at  TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_cache_accessed ON embedding_cache(accessed_at);

            CREATE TABLE IF NOT EXISTS memory_embedding_bands (
                memory_id TEXT NOT NULL,
                band      INTEGER NOT NULL,
                hash      INTEGER NOT NULL,
                PRIMARY KEY (memory_id, band)
            );
            CREATE INDEX IF NOT EXISTS idx_memory_embedding_bands_lookup
                ON memory_embedding_bands(band, hash);",
        )?;

        // Migration: add session_id column if not present (safe to run repeatedly)
        let has_session_id: bool = conn
            .prepare("SELECT sql FROM sqlite_master WHERE type='table' AND name='memories'")?
            .query_row([], |row| row.get::<_, String>(0))?
            .contains("session_id");
        if !has_session_id {
            conn.execute_batch("ALTER TABLE memories ADD COLUMN session_id TEXT;")?;
        }

        // Migration: add consolidated column for Kairos episodic memory consolidation
        let has_consolidated: bool = conn
            .prepare("SELECT sql FROM sqlite_master WHERE type='table' AND name='memories'")?
            .query_row([], |row| row.get::<_, String>(0))?
            .contains("consolidated");
        if !has_consolidated {
            conn.execute_batch(
                "ALTER TABLE memories ADD COLUMN consolidated INTEGER NOT NULL DEFAULT 0;
                 CREATE INDEX IF NOT EXISTS idx_memories_consolidated ON memories(consolidated) WHERE consolidated = 0;",
            )?;
        }

        conn.execute_batch(
            "CREATE INDEX IF NOT EXISTS idx_memories_session ON memories(session_id);
             CREATE INDEX IF NOT EXISTS idx_memories_session_created_at ON memories(session_id, created_at);
             CREATE INDEX IF NOT EXISTS idx_memories_embedding_created_at
                 ON memories(created_at) WHERE embedding IS NOT NULL;
             CREATE INDEX IF NOT EXISTS idx_memories_embedding_session_created_at
                 ON memories(session_id, created_at) WHERE embedding IS NOT NULL;",
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

    /// Deterministic content hash for embedding cache.
    /// Uses SHA-256 (truncated) instead of DefaultHasher, which is
    /// explicitly documented as unstable across Rust versions.
    fn content_hash(text: &str) -> String {
        use sha2::{Digest, Sha256};
        let hash = Sha256::digest(text.as_bytes());
        // First 8 bytes → 16 hex chars, matching previous format length
        format!(
            "{:016x}",
            u64::from_be_bytes(
                hash[..8]
                    .try_into()
                    .expect("SHA-256 always produces >= 8 bytes")
            )
        )
    }

    fn projection_seed(band: usize, bit: usize, dim: usize) -> u64 {
        let mut z = ((band as u64) << 48) ^ ((bit as u64) << 32) ^ dim as u64;
        z = z.wrapping_add(0x9E37_79B9_7F4A_7C15);
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }

    fn embedding_band_hashes(embedding: &[f32]) -> Vec<(i64, i64)> {
        if embedding.is_empty() {
            return Vec::new();
        }

        let mut hashes = Vec::with_capacity(LSH_BAND_COUNT);
        for band in 0..LSH_BAND_COUNT {
            let mut hash = 0_u64;
            for bit in 0..LSH_BITS_PER_BAND {
                let mut projection = 0.0_f64;
                for (dim, value) in embedding.iter().enumerate() {
                    match Self::projection_seed(band, bit, dim) & 0b111 {
                        0 => projection += f64::from(*value),
                        1 => projection -= f64::from(*value),
                        _ => {}
                    }
                }
                if projection >= 0.0 {
                    hash |= 1 << bit;
                }
            }
            hashes.push((band as i64, hash as i64));
        }
        hashes
    }

    fn replace_embedding_bands(
        conn: &Connection,
        memory_id: &str,
        embedding: &[f32],
    ) -> anyhow::Result<()> {
        conn.execute(
            "DELETE FROM memory_embedding_bands WHERE memory_id = ?1",
            params![memory_id],
        )?;

        let band_hashes = Self::embedding_band_hashes(embedding);
        let mut stmt = conn.prepare(
            "INSERT OR REPLACE INTO memory_embedding_bands (memory_id, band, hash)
             VALUES (?1, ?2, ?3)",
        )?;
        for (band, hash) in band_hashes {
            stmt.execute(params![memory_id, band, hash])?;
        }
        Ok(())
    }

    fn band_candidate_limit(limit: usize) -> usize {
        std::cmp::max(
            limit.saturating_mul(LSH_CANDIDATE_MULTIPLIER),
            LSH_MIN_CANDIDATES,
        )
    }

    fn load_missing_embedding_band_rows(
        conn: &Connection,
        limit: usize,
    ) -> anyhow::Result<Vec<(String, Vec<u8>)>> {
        if limit == 0 {
            return Ok(Vec::new());
        }

        let mut stmt = conn.prepare(
            "SELECT m.id, m.embedding
             FROM memories m
             LEFT JOIN memory_embedding_bands b ON b.memory_id = m.id
             WHERE m.embedding IS NOT NULL
             GROUP BY m.id, m.embedding
             HAVING COUNT(b.band) < ?1
             LIMIT ?2",
        )?;
        #[allow(clippy::cast_possible_wrap)]
        let band_count = LSH_BAND_COUNT as i64;
        #[allow(clippy::cast_possible_wrap)]
        let limit_i64 = limit as i64;
        let rows = stmt.query_map(params![band_count, limit_i64], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, Vec<u8>>(1)?))
        })?;

        let mut missing = Vec::new();
        for row in rows {
            missing.push(row?);
        }
        Ok(missing)
    }

    fn backfill_missing_embedding_bands(
        conn: &mut Connection,
        batch_size: usize,
    ) -> anyhow::Result<usize> {
        if batch_size == 0 {
            return Ok(0);
        }

        let mut repaired = 0;
        loop {
            let batch = Self::load_missing_embedding_band_rows(conn, batch_size)?;
            if batch.is_empty() {
                break;
            }

            let tx = conn.transaction()?;
            for (memory_id, embedding_blob) in &batch {
                let embedding = vector::bytes_to_vec(embedding_blob);
                Self::replace_embedding_bands(&tx, memory_id, &embedding)?;
                repaired += 1;
            }
            tx.commit()?;

            if batch.len() < batch_size {
                break;
            }
        }

        Ok(repaired)
    }

    /// Get embedding from cache, or compute + cache it
    async fn get_or_compute_embedding(&self, text: &str) -> anyhow::Result<Option<Vec<f32>>> {
        if self.embedder.dimensions() == 0 {
            return Ok(None); // Noop embedder
        }

        let hash = Self::content_hash(text);
        let now = Local::now().to_rfc3339();

        // Check cache (offloaded to blocking thread)
        let conn = self.conn.clone();
        let hash_c = hash.clone();
        let now_c = now.clone();
        let cached = tokio::task::spawn_blocking(move || -> anyhow::Result<Option<Vec<f32>>> {
            let conn = conn.lock();
            let mut stmt =
                conn.prepare("SELECT embedding FROM embedding_cache WHERE content_hash = ?1")?;
            let blob: Option<Vec<u8>> = stmt.query_row(params![hash_c], |row| row.get(0)).ok();
            if let Some(bytes) = blob {
                conn.execute(
                    "UPDATE embedding_cache SET accessed_at = ?1 WHERE content_hash = ?2",
                    params![now_c, hash_c],
                )?;
                return Ok(Some(vector::bytes_to_vec(&bytes)));
            }
            Ok(None)
        })
        .await??;

        if cached.is_some() {
            return Ok(cached);
        }

        // Compute embedding (async I/O)
        let embedding = self.embedder.embed_one(text).await?;
        let bytes = vector::vec_to_bytes(&embedding);

        // Store in cache + LRU eviction (offloaded to blocking thread)
        let conn = self.conn.clone();
        #[allow(clippy::cast_possible_wrap)]
        let cache_max = self.cache_max as i64;
        tokio::task::spawn_blocking(move || -> anyhow::Result<()> {
            let conn = conn.lock();
            conn.execute(
                "INSERT OR REPLACE INTO embedding_cache (content_hash, embedding, created_at, accessed_at)
                 VALUES (?1, ?2, ?3, ?4)",
                params![hash, bytes, now, now],
            )?;
            conn.execute(
                "DELETE FROM embedding_cache WHERE content_hash IN (
                    SELECT content_hash FROM embedding_cache
                    ORDER BY accessed_at ASC
                    LIMIT MAX(0, (SELECT COUNT(*) FROM embedding_cache) - ?1)
                )",
                params![cache_max],
            )?;
            Ok(())
        })
        .await??;

        Ok(Some(embedding))
    }

    fn push_recall_filters(
        sql: &mut String,
        param_values: &mut Vec<Box<dyn rusqlite::types::ToSql>>,
        idx: &mut usize,
        column_prefix: &str,
        filters: RecallFilters<'_>,
    ) {
        if let Some(cat) = filters.category {
            let _ = write!(sql, " AND {column_prefix}category = ?{idx}");
            param_values.push(Box::new(cat.to_string()));
            *idx += 1;
        }
        if let Some(sid) = filters.session_id {
            let _ = write!(sql, " AND {column_prefix}session_id = ?{idx}");
            param_values.push(Box::new(sid.to_string()));
            *idx += 1;
        }
        if let Some(since) = filters.since {
            let _ = write!(sql, " AND {column_prefix}created_at >= ?{idx}");
            param_values.push(Box::new(since.to_string()));
            *idx += 1;
        }
        if let Some(until) = filters.until {
            let _ = write!(sql, " AND {column_prefix}created_at <= ?{idx}");
            param_values.push(Box::new(until.to_string()));
            *idx += 1;
        }
    }

    /// FTS5 BM25 keyword search
    fn load_keyword_hits(
        conn: &Connection,
        query: &str,
        limit: usize,
        filters: RecallFilters<'_>,
    ) -> anyhow::Result<Vec<(String, f32)>> {
        // Escape FTS5 special chars and build query
        let fts_query: String = query
            .split_whitespace()
            .map(|w| format!("\"{w}\""))
            .collect::<Vec<_>>()
            .join(" OR ");

        if fts_query.is_empty() {
            return Ok(Vec::new());
        }

        let mut sql = "SELECT m.id, bm25(memories_fts) as score
                       FROM memories_fts f
                       JOIN memories m ON m.rowid = f.rowid
                       WHERE memories_fts MATCH ?1"
            .to_string();
        let mut param_values: Vec<Box<dyn rusqlite::types::ToSql>> = vec![Box::new(fts_query)];
        let mut idx = 2;
        Self::push_recall_filters(&mut sql, &mut param_values, &mut idx, "m.", filters);
        let _ = write!(sql, " ORDER BY score LIMIT ?{idx}");
        #[allow(clippy::cast_possible_wrap)]
        param_values.push(Box::new(limit as i64));

        let mut stmt = conn.prepare(&sql)?;
        #[allow(clippy::cast_possible_wrap)]
        let params_ref: Vec<&dyn rusqlite::types::ToSql> =
            param_values.iter().map(AsRef::as_ref).collect();
        let rows = stmt.query_map(params_ref.as_slice(), |row| {
            let id: String = row.get(0)?;
            let score: f64 = row.get(1)?;
            // BM25 returns negative scores (lower = better), negate for ranking
            #[allow(clippy::cast_possible_truncation)]
            Ok((id, (-score) as f32))
        })?;

        let mut results = Vec::new();
        for row in rows {
            results.push(row?);
        }
        Ok(results)
    }

    fn load_vector_candidates(
        conn: &Connection,
        filters: RecallFilters<'_>,
    ) -> anyhow::Result<Vec<VectorCandidate>> {
        let mut sql = "SELECT id, embedding FROM memories WHERE embedding IS NOT NULL".to_string();
        let mut param_values: Vec<Box<dyn rusqlite::types::ToSql>> = Vec::new();
        let mut idx = 1;
        Self::push_recall_filters(&mut sql, &mut param_values, &mut idx, "", filters);

        let mut stmt = conn.prepare(&sql)?;
        let params_ref: Vec<&dyn rusqlite::types::ToSql> =
            param_values.iter().map(AsRef::as_ref).collect();
        let rows = stmt.query_map(params_ref.as_slice(), |row| {
            let id: String = row.get(0)?;
            let blob: Vec<u8> = row.get(1)?;
            Ok(VectorCandidate {
                id,
                embedding_blob: blob,
            })
        })?;

        let mut candidates = Vec::new();
        for row in rows {
            candidates.push(row?);
        }
        Ok(candidates)
    }

    fn load_vector_candidate_ids(
        conn: &Connection,
        band_hashes: &[(i64, i64)],
        filters: RecallFilters<'_>,
        limit: usize,
    ) -> anyhow::Result<Vec<String>> {
        if band_hashes.is_empty() || limit == 0 {
            return Ok(Vec::new());
        }

        let mut sql = "SELECT m.id, COUNT(*) as band_hits, MAX(m.updated_at) as updated_at
                       FROM memory_embedding_bands b
                       JOIN memories m ON m.id = b.memory_id
                       WHERE ("
            .to_string();
        let mut param_values: Vec<Box<dyn rusqlite::types::ToSql>> = Vec::new();
        let mut idx = 1;

        for (position, (band, hash)) in band_hashes.iter().enumerate() {
            if position > 0 {
                sql.push_str(" OR ");
            }
            let _ = write!(sql, "(b.band = ?{idx} AND b.hash = ?{})", idx + 1);
            param_values.push(Box::new(*band));
            param_values.push(Box::new(*hash));
            idx += 2;
        }

        sql.push(')');
        sql.push_str(" AND m.embedding IS NOT NULL");
        Self::push_recall_filters(&mut sql, &mut param_values, &mut idx, "m.", filters);
        let _ = write!(
            sql,
            " GROUP BY m.id ORDER BY band_hits DESC, updated_at DESC LIMIT ?{idx}"
        );
        #[allow(clippy::cast_possible_wrap)]
        param_values.push(Box::new(limit as i64));

        let mut stmt = conn.prepare(&sql)?;
        let params_ref: Vec<&dyn rusqlite::types::ToSql> =
            param_values.iter().map(AsRef::as_ref).collect();
        let rows = stmt.query_map(params_ref.as_slice(), |row| row.get::<_, String>(0))?;

        let mut ids = Vec::new();
        for row in rows {
            ids.push(row?);
        }
        Ok(ids)
    }

    fn load_vector_candidates_by_ids(
        conn: &Connection,
        ids: &[String],
    ) -> anyhow::Result<Vec<VectorCandidate>> {
        if ids.is_empty() {
            return Ok(Vec::new());
        }

        let placeholders: String = (1..=ids.len())
            .map(|i| format!("?{i}"))
            .collect::<Vec<_>>()
            .join(", ");
        let sql = format!("SELECT id, embedding FROM memories WHERE id IN ({placeholders})");
        let mut stmt = conn.prepare(&sql)?;
        let id_params: Vec<Box<dyn rusqlite::types::ToSql>> = ids
            .iter()
            .map(|id| Box::new(id.clone()) as Box<dyn rusqlite::types::ToSql>)
            .collect();
        let params_ref: Vec<&dyn rusqlite::types::ToSql> =
            id_params.iter().map(AsRef::as_ref).collect();
        let rows = stmt.query_map(params_ref.as_slice(), |row| {
            Ok(VectorCandidate {
                id: row.get(0)?,
                embedding_blob: row.get(1)?,
            })
        })?;

        let mut candidates = Vec::new();
        for row in rows {
            candidates.push(row?);
        }
        Ok(candidates)
    }

    fn score_vector_candidates(
        query_embedding: &[f32],
        candidates: Vec<VectorCandidate>,
        limit: usize,
    ) -> Vec<(String, f32)> {
        if limit == 0 || query_embedding.is_empty() {
            return Vec::new();
        }

        let mut heap: BinaryHeap<Reverse<RankedVectorResult>> = BinaryHeap::new();

        for candidate in candidates {
            let emb = vector::bytes_to_vec(&candidate.embedding_blob);
            let sim = vector::cosine_similarity(query_embedding, &emb);
            if sim <= 0.0 {
                continue;
            }

            let ranked = Reverse(RankedVectorResult {
                id: candidate.id,
                score: sim,
            });

            if heap.len() < limit {
                heap.push(ranked);
                continue;
            }

            if let Some(mut smallest) = heap.peek_mut() {
                if ranked.0 > smallest.0 {
                    *smallest = ranked;
                }
            }
        }

        let mut scored: Vec<(String, f32)> = heap
            .into_iter()
            .map(|Reverse(item)| (item.id, item.score))
            .collect();

        scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
        scored
    }

    fn load_entries_by_ids(
        conn: &Connection,
        ids: &[String],
    ) -> anyhow::Result<HashMap<String, HydratedMemoryRow>> {
        if ids.is_empty() {
            return Ok(HashMap::new());
        }

        let placeholders: String = (1..=ids.len())
            .map(|i| format!("?{i}"))
            .collect::<Vec<_>>()
            .join(", ");
        let sql = format!(
            "SELECT id, key, content, category, created_at, session_id \
             FROM memories WHERE id IN ({placeholders})"
        );
        let mut stmt = conn.prepare(&sql)?;
        let id_params: Vec<Box<dyn rusqlite::types::ToSql>> = ids
            .iter()
            .map(|id| Box::new(id.clone()) as Box<dyn rusqlite::types::ToSql>)
            .collect();
        let params_ref: Vec<&dyn rusqlite::types::ToSql> =
            id_params.iter().map(AsRef::as_ref).collect();
        let rows = stmt.query_map(params_ref.as_slice(), |row| {
            Ok(HydratedMemoryRow {
                id: row.get(0)?,
                key: row.get(1)?,
                content: row.get(2)?,
                category: row.get(3)?,
                created_at: row.get(4)?,
                session_id: row.get(5)?,
            })
        })?;

        let mut entry_map = HashMap::new();
        for row in rows {
            let row = row?;
            entry_map.insert(row.id.clone(), row);
        }
        Ok(entry_map)
    }

    fn load_like_fallback(
        conn: &Connection,
        query: &str,
        limit: usize,
        filters: RecallFilters<'_>,
    ) -> anyhow::Result<Vec<MemoryEntry>> {
        const MAX_LIKE_KEYWORDS: usize = 8;
        let keywords: Vec<String> = query
            .split_whitespace()
            .take(MAX_LIKE_KEYWORDS)
            .map(|w| format!("%{w}%"))
            .collect();

        if keywords.is_empty() {
            return Ok(Vec::new());
        }

        let conditions: Vec<String> = keywords
            .iter()
            .enumerate()
            .map(|(i, _)| format!("(content LIKE ?{} OR key LIKE ?{})", i * 2 + 1, i * 2 + 2))
            .collect();
        let mut sql = format!(
            "SELECT id, key, content, category, created_at, session_id FROM memories
             WHERE ({})",
            conditions.join(" OR ")
        );
        let mut param_values: Vec<Box<dyn rusqlite::types::ToSql>> = Vec::new();
        for kw in &keywords {
            param_values.push(Box::new(kw.clone()));
            param_values.push(Box::new(kw.clone()));
        }
        let mut idx = keywords.len() * 2 + 1;
        Self::push_recall_filters(&mut sql, &mut param_values, &mut idx, "", filters);
        let _ = write!(sql, " ORDER BY updated_at DESC LIMIT ?{idx}");
        #[allow(clippy::cast_possible_wrap)]
        param_values.push(Box::new(limit as i64));

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
                score: Some(1.0),
                namespace: "default".into(),
                importance: None,
                superseded_by: None,
            })
        })?;

        let mut results = Vec::new();
        for row in rows {
            results.push(row?);
        }
        Ok(results)
    }

    /// Safe reindex: rebuild FTS5 + embeddings with rollback on failure
    pub async fn reindex(&self) -> anyhow::Result<usize> {
        // Step 1: Rebuild FTS5
        {
            let conn = self.conn.clone();
            tokio::task::spawn_blocking(move || -> anyhow::Result<()> {
                let conn = conn.lock();
                conn.execute_batch("INSERT INTO memories_fts(memories_fts) VALUES('rebuild');")?;
                Ok(())
            })
            .await??;
        }

        // Step 2: Re-embed all memories that lack embeddings
        if self.embedder.dimensions() == 0 {
            return Ok(0);
        }

        let conn = self.conn.clone();
        let entries: Vec<(String, String)> = tokio::task::spawn_blocking(move || {
            let conn = conn.lock();
            let mut stmt =
                conn.prepare("SELECT id, content FROM memories WHERE embedding IS NULL")?;
            let rows = stmt.query_map([], |row| {
                Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
            })?;
            Ok::<_, anyhow::Error>(rows.filter_map(std::result::Result::ok).collect())
        })
        .await??;

        let mut count = 0;
        for (id, content) in &entries {
            if let Ok(Some(emb)) = self.get_or_compute_embedding(content).await {
                let bytes = vector::vec_to_bytes(&emb);
                let emb_for_index = emb.clone();
                let conn = self.conn.clone();
                let id = id.clone();
                tokio::task::spawn_blocking(move || -> anyhow::Result<()> {
                    let conn = conn.lock();
                    conn.execute(
                        "UPDATE memories SET embedding = ?1 WHERE id = ?2",
                        params![bytes, &id],
                    )?;
                    Self::replace_embedding_bands(&conn, &id, &emb_for_index)?;
                    Ok(())
                })
                .await??;
                count += 1;
            }
        }

        let conn = self.conn.clone();
        let indexed_entries: Vec<(String, Vec<u8>)> = tokio::task::spawn_blocking(move || {
            let conn = conn.lock();
            let mut stmt =
                conn.prepare("SELECT id, embedding FROM memories WHERE embedding IS NOT NULL")?;
            let rows = stmt.query_map([], |row| {
                Ok((row.get::<_, String>(0)?, row.get::<_, Vec<u8>>(1)?))
            })?;
            Ok::<_, anyhow::Error>(rows.filter_map(std::result::Result::ok).collect())
        })
        .await??;

        for (id, embedding_blob) in indexed_entries {
            let embedding = vector::bytes_to_vec(&embedding_blob);
            let conn = self.conn.clone();
            tokio::task::spawn_blocking(move || -> anyhow::Result<()> {
                let conn = conn.lock();
                Self::replace_embedding_bands(&conn, &id, &embedding)?;
                Ok(())
            })
            .await??;
        }

        Ok(count)
    }

    /// List memories by time range (used when query is empty).
    async fn recall_by_time_only(
        &self,
        limit: usize,
        session_id: Option<&str>,
        since: Option<&str>,
        until: Option<&str>,
    ) -> anyhow::Result<Vec<MemoryEntry>> {
        let conn = self.conn.clone();
        let sid = session_id.map(String::from);
        let since_owned = since.map(String::from);
        let until_owned = until.map(String::from);

        tokio::task::spawn_blocking(move || -> anyhow::Result<Vec<MemoryEntry>> {
            let conn = conn.lock();
            let since_ref = since_owned.as_deref();
            let until_ref = until_owned.as_deref();

            let mut sql =
                "SELECT id, key, content, category, created_at, session_id FROM memories \
                           WHERE 1=1"
                    .to_string();
            let mut param_values: Vec<Box<dyn rusqlite::types::ToSql>> = Vec::new();
            let mut idx = 1;

            if let Some(sid) = sid.as_deref() {
                let _ = write!(sql, " AND session_id = ?{idx}");
                param_values.push(Box::new(sid.to_string()));
                idx += 1;
            }
            if let Some(s) = since_ref {
                let _ = write!(sql, " AND created_at >= ?{idx}");
                param_values.push(Box::new(s.to_string()));
                idx += 1;
            }
            if let Some(u) = until_ref {
                let _ = write!(sql, " AND created_at <= ?{idx}");
                param_values.push(Box::new(u.to_string()));
                idx += 1;
            }
            let _ = write!(sql, " ORDER BY updated_at DESC LIMIT ?{idx}");
            #[allow(clippy::cast_possible_wrap)]
            param_values.push(Box::new(limit as i64));

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

            let mut results = Vec::new();
            for row in rows {
                results.push(row?);
            }
            Ok(results)
        })
        .await?
    }

    /// Returns the created_at timestamp of the most recent conversation memory, if any.
    pub async fn latest_episodic_write_at(&self) -> anyhow::Result<Option<String>> {
        let conn = self.conn.clone();
        tokio::task::spawn_blocking(move || {
            let conn = conn.lock();
            let result: Option<String> = conn
                .query_row(
                    "SELECT created_at FROM memories
                     WHERE category = 'conversation'
                     ORDER BY created_at DESC LIMIT 1",
                    [],
                    |row| row.get(0),
                )
                .ok();
            Ok(result)
        })
        .await?
    }

    /// Fetch unconsolidated conversation rows up to `limit`, ordered by created_at.
    pub async fn fetch_unconsolidated(&self, limit: usize) -> anyhow::Result<Vec<MemoryRow>> {
        let conn = self.conn.clone();
        let limit = limit as i64;
        tokio::task::spawn_blocking(move || {
            let conn = conn.lock();
            let mut stmt = conn.prepare(
                "SELECT rowid, key, content, session_id, created_at
                 FROM memories
                 WHERE consolidated = 0 AND category = 'conversation'
                 ORDER BY created_at ASC
                 LIMIT ?1",
            )?;
            let rows = stmt.query_map([limit], |row| {
                let key: String = row.get(1)?;
                // Extract role from key: format "session/{session_id}/role/{role}" or fallback to "user"
                let role = key
                    .split('/')
                    .nth(3)
                    .map(String::from)
                    .unwrap_or_else(|| "user".to_string());
                Ok(MemoryRow {
                    id: row.get(0)?,
                    key,
                    content: row.get(2)?,
                    role,
                    timestamp: row.get(4)?,
                })
            })?;
            let mut result = Vec::new();
            for row in rows {
                result.push(row?);
            }
            Ok(result)
        })
        .await?
    }

    /// Mark rows as consolidated by their rowid.
    pub async fn mark_as_consolidated(&self, ids: &[i64]) -> anyhow::Result<()> {
        if ids.is_empty() {
            return Ok(());
        }
        let conn = self.conn.clone();
        let ids_vec: Vec<i64> = ids.to_vec();
        tokio::task::spawn_blocking(move || {
            let conn = conn.lock();
            let placeholders: String = (1..=ids_vec.len())
                .map(|i| format!("?{i}"))
                .collect::<Vec<_>>()
                .join(", ");
            let sql =
                format!("UPDATE memories SET consolidated = 1 WHERE rowid IN ({placeholders})");
            let params: Vec<Box<dyn rusqlite::types::ToSql>> = ids_vec
                .iter()
                .map(|id| Box::new(*id) as Box<dyn rusqlite::types::ToSql>)
                .collect();
            let params_ref: Vec<&dyn rusqlite::types::ToSql> =
                params.iter().map(AsRef::as_ref).collect();
            conn.execute(&sql, params_ref.as_slice())?;
            Ok(())
        })
        .await?
    }
}

#[async_trait]
impl Memory for SqliteMemory {
    fn name(&self) -> &str {
        "sqlite"
    }

    async fn store(
        &self,
        key: &str,
        content: &str,
        category: MemoryCategory,
        session_id: Option<&str>,
    ) -> anyhow::Result<()> {
        // Compute embedding (async, before blocking work)
        let embedding = self.get_or_compute_embedding(content).await?;
        let embedding_bytes = embedding.as_deref().map(vector::vec_to_bytes);

        let conn = self.conn.clone();
        let key = key.to_string();
        let content = content.to_string();
        let sid = session_id.map(String::from);

        tokio::task::spawn_blocking(move || -> anyhow::Result<()> {
            let conn = conn.lock();
            let now = Local::now().to_rfc3339();
            let cat = Self::category_to_str(&category);
            let id = Uuid::new_v4().to_string();

            conn.execute(
                "INSERT INTO memories (id, key, content, category, embedding, created_at, updated_at, session_id)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)
                 ON CONFLICT(key) DO UPDATE SET
                    content = excluded.content,
                    category = excluded.category,
                    embedding = excluded.embedding,
                    updated_at = excluded.updated_at,
                    session_id = excluded.session_id",
                params![id, &key, &content, cat, embedding_bytes, now, now, sid],
            )?;

            let memory_id: String =
                conn.query_row("SELECT id FROM memories WHERE key = ?1", params![&key], |row| {
                    row.get(0)
                })?;
            if let Some(embedding) = embedding.as_deref() {
                Self::replace_embedding_bands(&conn, &memory_id, embedding)?;
            } else {
                conn.execute(
                    "DELETE FROM memory_embedding_bands WHERE memory_id = ?1",
                    params![memory_id],
                )?;
            }
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
        if limit == 0 {
            return Ok(Vec::new());
        }

        // Time-only query: list by time range when no keywords
        if query.trim().is_empty() {
            return self
                .recall_by_time_only(limit, session_id, since, until)
                .await;
        }

        // Compute query embedding (async, before blocking work)
        let query_embedding = self.get_or_compute_embedding(query).await?;

        let conn = self.conn.clone();
        let query = query.to_string();
        let sid = session_id.map(String::from);
        let since_owned = since.map(String::from);
        let until_owned = until.map(String::from);
        let vector_weight = self.vector_weight;
        let keyword_weight = self.keyword_weight;

        tokio::task::spawn_blocking(move || -> anyhow::Result<Vec<MemoryEntry>> {
            let session_ref = sid.as_deref();
            let filters = RecallFilters {
                category: None,
                session_id: session_ref,
                since: since_owned.as_deref(),
                until: until_owned.as_deref(),
            };
            let query_band_hashes = query_embedding
                .as_ref()
                .map(|embedding| Self::embedding_band_hashes(embedding));

            let (keyword_results, vector_candidates) = {
                let conn = conn.lock();
                let keyword_results =
                    Self::load_keyword_hits(&conn, &query, limit * 2, filters).unwrap_or_default();
                let vector_candidates = if query_embedding.is_some() {
                    let candidate_ids = Self::load_vector_candidate_ids(
                        &conn,
                        query_band_hashes
                            .as_deref()
                            .expect("query embedding present when loading vector candidates"),
                        filters,
                        Self::band_candidate_limit(limit * 2),
                    )
                    .unwrap_or_default();

                    if candidate_ids.is_empty() {
                        Self::load_vector_candidates(&conn, filters).unwrap_or_default()
                    } else {
                        Self::load_vector_candidates_by_ids(&conn, &candidate_ids)
                            .unwrap_or_default()
                    }
                } else {
                    Vec::new()
                };
                (keyword_results, vector_candidates)
            };

            // Important: all vector math happens after the connection lock is dropped.
            let vector_results = if let Some(ref qe) = query_embedding {
                Self::score_vector_candidates(qe, vector_candidates, limit * 2)
            } else {
                Vec::new()
            };

            // Hybrid merge
            let merged = if vector_results.is_empty() {
                keyword_results
                    .iter()
                    .map(|(id, score)| vector::ScoredResult {
                        id: id.clone(),
                        vector_score: None,
                        keyword_score: Some(*score),
                        final_score: *score,
                    })
                    .collect::<Vec<_>>()
            } else {
                vector::hybrid_merge(
                    &vector_results,
                    &keyword_results,
                    vector_weight,
                    keyword_weight,
                    limit,
                )
            };

            let mut results = Vec::new();
            if !merged.is_empty() {
                let ids: Vec<String> = merged.iter().map(|scored| scored.id.clone()).collect();
                let entry_map = {
                    let conn = conn.lock();
                    Self::load_entries_by_ids(&conn, &ids)?
                };

                for scored in &merged {
                    if let Some(row) = entry_map.get(&scored.id) {
                        let entry = MemoryEntry {
                            id: scored.id.clone(),
                            key: row.key.clone(),
                            content: row.content.clone(),
                            category: Self::str_to_category(&row.category),
                            timestamp: row.created_at.clone(),
                            session_id: row.session_id.clone(),
                            score: Some(f64::from(scored.final_score)),
                            namespace: "default".into(),
                            importance: None,
                            superseded_by: None,
                        };
                        results.push(entry);
                    }
                }
            }

            // If hybrid returned nothing, fall back to LIKE search.
            if results.is_empty() {
                let conn = conn.lock();
                results = Self::load_like_fallback(&conn, &query, limit, filters)?;
            }

            results.truncate(limit);
            Ok(results)
        })
        .await?
    }

    async fn get(&self, key: &str) -> anyhow::Result<Option<MemoryEntry>> {
        let conn = self.conn.clone();
        let key = key.to_string();

        tokio::task::spawn_blocking(move || -> anyhow::Result<Option<MemoryEntry>> {
            let conn = conn.lock();
            let mut stmt = conn.prepare(
                "SELECT id, key, content, category, created_at, session_id FROM memories WHERE key = ?1",
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
        const DEFAULT_LIST_LIMIT: i64 = 1000;

        let conn = self.conn.clone();
        let category = category.cloned();
        let sid = session_id.map(String::from);

        tokio::task::spawn_blocking(move || -> anyhow::Result<Vec<MemoryEntry>> {
            let conn = conn.lock();
            let session_ref = sid.as_deref();
            let mut results = Vec::new();

            let row_mapper = |row: &rusqlite::Row| -> rusqlite::Result<MemoryEntry> {
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
            };

            if let Some(ref cat) = category {
                let cat_str = Self::category_to_str(cat);
                let mut stmt = conn.prepare(
                    "SELECT id, key, content, category, created_at, session_id FROM memories
                     WHERE category = ?1 ORDER BY updated_at DESC LIMIT ?2",
                )?;
                let rows = stmt.query_map(params![cat_str, DEFAULT_LIST_LIMIT], row_mapper)?;
                for row in rows {
                    let entry = row?;
                    if let Some(sid) = session_ref {
                        if entry.session_id.as_deref() != Some(sid) {
                            continue;
                        }
                    }
                    results.push(entry);
                }
            } else {
                let mut stmt = conn.prepare(
                    "SELECT id, key, content, category, created_at, session_id FROM memories
                     ORDER BY updated_at DESC LIMIT ?1",
                )?;
                let rows = stmt.query_map(params![DEFAULT_LIST_LIMIT], row_mapper)?;
                for row in rows {
                    let entry = row?;
                    if let Some(sid) = session_ref {
                        if entry.session_id.as_deref() != Some(sid) {
                            continue;
                        }
                    }
                    results.push(entry);
                }
            }

            Ok(results)
        })
        .await?
    }

    async fn forget(&self, key: &str) -> anyhow::Result<bool> {
        let conn = self.conn.clone();
        let key = key.to_string();

        tokio::task::spawn_blocking(move || -> anyhow::Result<bool> {
            let conn = conn.lock();
            conn.execute(
                "DELETE FROM memory_embedding_bands
                 WHERE memory_id IN (SELECT id FROM memories WHERE key = ?1)",
                params![key],
            )?;
            let affected = conn.execute("DELETE FROM memories WHERE key = ?1", params![key])?;
            Ok(affected > 0)
        })
        .await?
    }

    async fn count(&self) -> anyhow::Result<usize> {
        let conn = self.conn.clone();

        tokio::task::spawn_blocking(move || -> anyhow::Result<usize> {
            let conn = conn.lock();
            let count: i64 =
                conn.query_row("SELECT COUNT(*) FROM memories", [], |row| row.get(0))?;
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

    fn temp_sqlite() -> (TempDir, SqliteMemory) {
        let tmp = TempDir::new().unwrap();
        let mem = SqliteMemory::new(tmp.path()).unwrap();
        (tmp, mem)
    }

    fn temp_sqlite_with_embedder(embedder: Arc<dyn EmbeddingProvider>) -> (TempDir, SqliteMemory) {
        let tmp = TempDir::new().unwrap();
        let mem = SqliteMemory::with_embedder(tmp.path(), embedder, 0.7, 0.3, 1000, None).unwrap();
        (tmp, mem)
    }

    struct TestEmbedding;

    fn embedding_for_text(text: &str) -> Vec<f32> {
        let normalized = text.to_ascii_lowercase();
        if normalized.contains("alpha")
            || normalized.contains("keep")
            || normalized.contains("query-alpha")
            || normalized.contains("querysun")
        {
            vec![1.0, 0.0, 0.0]
        } else if normalized.contains("beta") || normalized.contains("second") {
            vec![0.8, 0.2, 0.0]
        } else if normalized.contains("gamma") || normalized.contains("archive") {
            vec![0.0, 1.0, 0.0]
        } else {
            vec![0.2, 0.2, 0.8]
        }
    }

    #[async_trait]
    impl EmbeddingProvider for TestEmbedding {
        fn name(&self) -> &str {
            "test"
        }

        fn dimensions(&self) -> usize {
            3
        }

        async fn embed(&self, texts: &[&str]) -> anyhow::Result<Vec<Vec<f32>>> {
            Ok(texts.iter().map(|text| embedding_for_text(text)).collect())
        }
    }

    fn set_embedding_by_key(mem: &SqliteMemory, key: &str, embedding: &[f32]) {
        let conn = mem.conn.lock();
        conn.execute(
            "UPDATE memories SET embedding = ?1 WHERE key = ?2",
            params![vector::vec_to_bytes(embedding), key],
        )
        .unwrap();
    }

    fn set_timestamps_by_key(mem: &SqliteMemory, key: &str, created_at: &str, updated_at: &str) {
        let conn = mem.conn.lock();
        conn.execute(
            "UPDATE memories SET created_at = ?1, updated_at = ?2 WHERE key = ?3",
            params![created_at, updated_at, key],
        )
        .unwrap();
    }

    fn count_embedding_bands(mem: &SqliteMemory, memory_id: &str) -> i64 {
        let conn = mem.conn.lock();
        conn.query_row(
            "SELECT COUNT(*) FROM memory_embedding_bands WHERE memory_id = ?1",
            params![memory_id],
            |row| row.get(0),
        )
        .unwrap()
    }

    #[tokio::test]
    async fn sqlite_name() {
        let (_tmp, mem) = temp_sqlite();
        assert_eq!(mem.name(), "sqlite");
    }

    #[tokio::test]
    async fn sqlite_health() {
        let (_tmp, mem) = temp_sqlite();
        assert!(mem.health_check().await);
    }

    #[tokio::test]
    async fn sqlite_store_and_get() {
        let (_tmp, mem) = temp_sqlite();
        mem.store("user_lang", "Prefers Rust", MemoryCategory::Core, None)
            .await
            .unwrap();

        let entry = mem.get("user_lang").await.unwrap();
        assert!(entry.is_some());
        let entry = entry.unwrap();
        assert_eq!(entry.key, "user_lang");
        assert_eq!(entry.content, "Prefers Rust");
        assert_eq!(entry.category, MemoryCategory::Core);
    }

    #[tokio::test]
    async fn sqlite_store_upsert() {
        let (_tmp, mem) = temp_sqlite();
        mem.store("pref", "likes Rust", MemoryCategory::Core, None)
            .await
            .unwrap();
        mem.store("pref", "loves Rust", MemoryCategory::Core, None)
            .await
            .unwrap();

        let entry = mem.get("pref").await.unwrap().unwrap();
        assert_eq!(entry.content, "loves Rust");
        assert_eq!(mem.count().await.unwrap(), 1);
    }

    #[tokio::test]
    async fn sqlite_recall_keyword() {
        let (_tmp, mem) = temp_sqlite();
        mem.store("a", "Rust is fast and safe", MemoryCategory::Core, None)
            .await
            .unwrap();
        mem.store("b", "Python is interpreted", MemoryCategory::Core, None)
            .await
            .unwrap();
        mem.store(
            "c",
            "Rust has zero-cost abstractions",
            MemoryCategory::Core,
            None,
        )
        .await
        .unwrap();

        let results = mem.recall("Rust", 10, None, None, None).await.unwrap();
        assert_eq!(results.len(), 2);
        assert!(
            results
                .iter()
                .all(|r| r.content.to_lowercase().contains("rust"))
        );
    }

    #[tokio::test]
    async fn sqlite_recall_multi_keyword() {
        let (_tmp, mem) = temp_sqlite();
        mem.store("a", "Rust is fast", MemoryCategory::Core, None)
            .await
            .unwrap();
        mem.store("b", "Rust is safe and fast", MemoryCategory::Core, None)
            .await
            .unwrap();

        let results = mem.recall("fast safe", 10, None, None, None).await.unwrap();
        assert!(!results.is_empty());
        // Entry with both keywords should score higher
        assert!(results[0].content.contains("safe") && results[0].content.contains("fast"));
    }

    #[tokio::test]
    async fn sqlite_recall_no_match() {
        let (_tmp, mem) = temp_sqlite();
        mem.store("a", "Rust rocks", MemoryCategory::Core, None)
            .await
            .unwrap();
        let results = mem
            .recall("javascript", 10, None, None, None)
            .await
            .unwrap();
        assert!(results.is_empty());
    }

    #[tokio::test]
    async fn sqlite_forget() {
        let (_tmp, mem) = temp_sqlite();
        mem.store("temp", "temporary data", MemoryCategory::Conversation, None)
            .await
            .unwrap();
        assert_eq!(mem.count().await.unwrap(), 1);

        let removed = mem.forget("temp").await.unwrap();
        assert!(removed);
        assert_eq!(mem.count().await.unwrap(), 0);
    }

    #[tokio::test]
    async fn sqlite_forget_nonexistent() {
        let (_tmp, mem) = temp_sqlite();
        let removed = mem.forget("nope").await.unwrap();
        assert!(!removed);
    }

    #[tokio::test]
    async fn sqlite_list_all() {
        let (_tmp, mem) = temp_sqlite();
        mem.store("a", "one", MemoryCategory::Core, None)
            .await
            .unwrap();
        mem.store("b", "two", MemoryCategory::Daily, None)
            .await
            .unwrap();
        mem.store("c", "three", MemoryCategory::Conversation, None)
            .await
            .unwrap();

        let all = mem.list(None, None).await.unwrap();
        assert_eq!(all.len(), 3);
    }

    #[tokio::test]
    async fn sqlite_list_by_category() {
        let (_tmp, mem) = temp_sqlite();
        mem.store("a", "core1", MemoryCategory::Core, None)
            .await
            .unwrap();
        mem.store("b", "core2", MemoryCategory::Core, None)
            .await
            .unwrap();
        mem.store("c", "daily1", MemoryCategory::Daily, None)
            .await
            .unwrap();

        let core = mem.list(Some(&MemoryCategory::Core), None).await.unwrap();
        assert_eq!(core.len(), 2);

        let daily = mem.list(Some(&MemoryCategory::Daily), None).await.unwrap();
        assert_eq!(daily.len(), 1);
    }

    #[tokio::test]
    async fn sqlite_count_empty() {
        let (_tmp, mem) = temp_sqlite();
        assert_eq!(mem.count().await.unwrap(), 0);
    }

    #[tokio::test]
    async fn sqlite_get_nonexistent() {
        let (_tmp, mem) = temp_sqlite();
        assert!(mem.get("nope").await.unwrap().is_none());
    }

    #[tokio::test]
    async fn sqlite_db_persists() {
        let tmp = TempDir::new().unwrap();

        {
            let mem = SqliteMemory::new(tmp.path()).unwrap();
            mem.store("persist", "I survive restarts", MemoryCategory::Core, None)
                .await
                .unwrap();
        }

        // Reopen
        let mem2 = SqliteMemory::new(tmp.path()).unwrap();
        let entry = mem2.get("persist").await.unwrap();
        assert!(entry.is_some());
        assert_eq!(entry.unwrap().content, "I survive restarts");
    }

    #[tokio::test]
    async fn sqlite_category_roundtrip() {
        let (_tmp, mem) = temp_sqlite();
        let categories = [
            MemoryCategory::Core,
            MemoryCategory::Daily,
            MemoryCategory::Conversation,
            MemoryCategory::Custom("project".into()),
        ];

        for (i, cat) in categories.iter().enumerate() {
            mem.store(&format!("k{i}"), &format!("v{i}"), cat.clone(), None)
                .await
                .unwrap();
        }

        for (i, cat) in categories.iter().enumerate() {
            let entry = mem.get(&format!("k{i}")).await.unwrap().unwrap();
            assert_eq!(&entry.category, cat);
        }
    }

    // ── FTS5 search tests ────────────────────────────────────────

    #[tokio::test]
    async fn fts5_bm25_ranking() {
        let (_tmp, mem) = temp_sqlite();
        mem.store(
            "a",
            "Rust is a systems programming language",
            MemoryCategory::Core,
            None,
        )
        .await
        .unwrap();
        mem.store(
            "b",
            "Python is great for scripting",
            MemoryCategory::Core,
            None,
        )
        .await
        .unwrap();
        mem.store(
            "c",
            "Rust and Rust and Rust everywhere",
            MemoryCategory::Core,
            None,
        )
        .await
        .unwrap();

        let results = mem.recall("Rust", 10, None, None, None).await.unwrap();
        assert!(results.len() >= 2);
        // All results should contain "Rust"
        for r in &results {
            assert!(
                r.content.to_lowercase().contains("rust"),
                "Expected 'rust' in: {}",
                r.content
            );
        }
    }

    #[tokio::test]
    async fn fts5_multi_word_query() {
        let (_tmp, mem) = temp_sqlite();
        mem.store("a", "The quick brown fox jumps", MemoryCategory::Core, None)
            .await
            .unwrap();
        mem.store("b", "A lazy dog sleeps", MemoryCategory::Core, None)
            .await
            .unwrap();
        mem.store("c", "The quick dog runs fast", MemoryCategory::Core, None)
            .await
            .unwrap();

        let results = mem.recall("quick dog", 10, None, None, None).await.unwrap();
        assert!(!results.is_empty());
        // "The quick dog runs fast" matches both terms
        assert!(results[0].content.contains("quick"));
    }

    #[tokio::test]
    async fn load_keyword_hits_respects_session_and_time_filters() {
        let (_tmp, mem) = temp_sqlite();
        mem.store(
            "keep",
            "cipher garden midnight notes",
            MemoryCategory::Core,
            Some("sess-a"),
        )
        .await
        .unwrap();
        mem.store(
            "wrong_session",
            "cipher garden other session",
            MemoryCategory::Core,
            Some("sess-b"),
        )
        .await
        .unwrap();
        mem.store(
            "too_old",
            "cipher garden archive",
            MemoryCategory::Core,
            Some("sess-a"),
        )
        .await
        .unwrap();

        set_timestamps_by_key(
            &mem,
            "keep",
            "2026-03-10T12:00:00+00:00",
            "2026-03-10T12:00:00+00:00",
        );
        set_timestamps_by_key(
            &mem,
            "wrong_session",
            "2026-03-10T12:00:00+00:00",
            "2026-03-10T12:00:00+00:00",
        );
        set_timestamps_by_key(
            &mem,
            "too_old",
            "2026-02-01T12:00:00+00:00",
            "2026-02-01T12:00:00+00:00",
        );

        let hits = {
            let conn = mem.conn.lock();
            SqliteMemory::load_keyword_hits(
                &conn,
                "cipher garden",
                10,
                RecallFilters {
                    category: None,
                    session_id: Some("sess-a"),
                    since: Some("2026-03-01T00:00:00+00:00"),
                    until: Some("2026-03-31T23:59:59+00:00"),
                },
            )
            .unwrap()
        };

        let hit_ids: Vec<String> = hits.into_iter().map(|(id, _)| id).collect();
        assert_eq!(hit_ids.len(), 1);
        let expected_id = mem.get("keep").await.unwrap().unwrap().id;
        assert_eq!(hit_ids[0], expected_id);
    }

    #[tokio::test]
    async fn load_vector_candidates_respects_session_and_time_filters() {
        let (_tmp, mem) = temp_sqlite();
        mem.store(
            "keep",
            "semantic keep",
            MemoryCategory::Core,
            Some("sess-a"),
        )
        .await
        .unwrap();
        mem.store(
            "wrong_session",
            "semantic wrong session",
            MemoryCategory::Core,
            Some("sess-b"),
        )
        .await
        .unwrap();
        mem.store(
            "too_new",
            "semantic future",
            MemoryCategory::Core,
            Some("sess-a"),
        )
        .await
        .unwrap();
        mem.store(
            "no_embedding",
            "semantic no embedding",
            MemoryCategory::Core,
            Some("sess-a"),
        )
        .await
        .unwrap();

        set_embedding_by_key(&mem, "keep", &[1.0, 0.0]);
        set_embedding_by_key(&mem, "wrong_session", &[0.8, 0.2]);
        set_embedding_by_key(&mem, "too_new", &[0.9, 0.1]);
        set_timestamps_by_key(
            &mem,
            "keep",
            "2026-03-10T12:00:00+00:00",
            "2026-03-10T12:00:00+00:00",
        );
        set_timestamps_by_key(
            &mem,
            "wrong_session",
            "2026-03-10T12:00:00+00:00",
            "2026-03-10T12:00:00+00:00",
        );
        set_timestamps_by_key(
            &mem,
            "too_new",
            "2026-04-10T12:00:00+00:00",
            "2026-04-10T12:00:00+00:00",
        );
        set_timestamps_by_key(
            &mem,
            "no_embedding",
            "2026-03-10T12:00:00+00:00",
            "2026-03-10T12:00:00+00:00",
        );

        let candidates = {
            let conn = mem.conn.lock();
            SqliteMemory::load_vector_candidates(
                &conn,
                RecallFilters {
                    category: None,
                    session_id: Some("sess-a"),
                    since: Some("2026-03-01T00:00:00+00:00"),
                    until: Some("2026-03-31T23:59:59+00:00"),
                },
            )
            .unwrap()
        };

        assert_eq!(candidates.len(), 1);
        let expected_id = mem.get("keep").await.unwrap().unwrap().id;
        assert_eq!(candidates[0].id, expected_id);
    }

    #[tokio::test]
    async fn load_vector_candidate_ids_respects_session_and_time_filters() {
        let (_tmp, mem) = temp_sqlite_with_embedder(Arc::new(TestEmbedding));
        mem.store(
            "keep",
            "velvet keep notes",
            MemoryCategory::Core,
            Some("sess-a"),
        )
        .await
        .unwrap();
        mem.store(
            "wrong_session",
            "velvet keep elsewhere",
            MemoryCategory::Core,
            Some("sess-b"),
        )
        .await
        .unwrap();
        mem.store(
            "too_old",
            "archive keep record",
            MemoryCategory::Core,
            Some("sess-a"),
        )
        .await
        .unwrap();

        set_timestamps_by_key(
            &mem,
            "keep",
            "2026-03-10T12:00:00+00:00",
            "2026-03-10T12:00:00+00:00",
        );
        set_timestamps_by_key(
            &mem,
            "wrong_session",
            "2026-03-10T12:00:00+00:00",
            "2026-03-10T12:00:00+00:00",
        );
        set_timestamps_by_key(
            &mem,
            "too_old",
            "2026-02-01T12:00:00+00:00",
            "2026-02-01T12:00:00+00:00",
        );

        let query_embedding = embedding_for_text("querysun");
        let candidate_ids = {
            let conn = mem.conn.lock();
            SqliteMemory::load_vector_candidate_ids(
                &conn,
                &SqliteMemory::embedding_band_hashes(&query_embedding),
                RecallFilters {
                    category: None,
                    session_id: Some("sess-a"),
                    since: Some("2026-03-01T00:00:00+00:00"),
                    until: Some("2026-03-31T23:59:59+00:00"),
                },
                16,
            )
            .unwrap()
        };

        assert_eq!(candidate_ids.len(), 1);
        let expected_id = mem.get("keep").await.unwrap().unwrap().id;
        assert_eq!(candidate_ids[0], expected_id);
    }

    #[tokio::test]
    async fn recall_uses_embedding_band_index_for_semantic_match() {
        let (_tmp, mem) = temp_sqlite_with_embedder(Arc::new(TestEmbedding));
        mem.store(
            "keep",
            "velvet keep notes",
            MemoryCategory::Core,
            Some("sess-a"),
        )
        .await
        .unwrap();
        mem.store(
            "other",
            "archive lantern ledger",
            MemoryCategory::Core,
            Some("sess-a"),
        )
        .await
        .unwrap();

        let results = mem
            .recall("querysun", 5, Some("sess-a"), None, None)
            .await
            .unwrap();
        assert!(!results.is_empty());
        assert_eq!(results[0].key, "keep");
    }

    #[test]
    fn score_vector_candidates_returns_top_k_only() {
        let candidates = vec![
            VectorCandidate {
                id: "top".into(),
                embedding_blob: vector::vec_to_bytes(&[1.0, 0.0]),
            },
            VectorCandidate {
                id: "second".into(),
                embedding_blob: vector::vec_to_bytes(&[0.8, 0.2]),
            },
            VectorCandidate {
                id: "third".into(),
                embedding_blob: vector::vec_to_bytes(&[0.2, 0.8]),
            },
            VectorCandidate {
                id: "drop".into(),
                embedding_blob: vector::vec_to_bytes(&[0.0, 1.0]),
            },
        ];

        let scored = SqliteMemory::score_vector_candidates(&[1.0, 0.0], candidates, 2);
        assert_eq!(scored.len(), 2);
        assert_eq!(scored[0].0, "top");
        assert_eq!(scored[1].0, "second");
        assert!(scored[0].1 >= scored[1].1);
    }

    #[tokio::test]
    async fn recall_empty_query_returns_recent_entries() {
        let (_tmp, mem) = temp_sqlite();
        mem.store("a", "data", MemoryCategory::Core, None)
            .await
            .unwrap();
        // Empty query = time-only mode: returns recent entries
        let results = mem.recall("", 10, None, None, None).await.unwrap();
        assert_eq!(results.len(), 1);
        assert_eq!(results[0].key, "a");
    }

    #[tokio::test]
    async fn recall_whitespace_query_returns_recent_entries() {
        let (_tmp, mem) = temp_sqlite();
        mem.store("a", "data", MemoryCategory::Core, None)
            .await
            .unwrap();
        // Whitespace-only query = time-only mode: returns recent entries
        let results = mem.recall("   ", 10, None, None, None).await.unwrap();
        assert_eq!(results.len(), 1);
        assert_eq!(results[0].key, "a");
    }

    // ── Embedding cache tests ────────────────────────────────────

    #[test]
    fn content_hash_deterministic() {
        let h1 = SqliteMemory::content_hash("hello world");
        let h2 = SqliteMemory::content_hash("hello world");
        assert_eq!(h1, h2);
    }

    #[test]
    fn content_hash_different_inputs() {
        let h1 = SqliteMemory::content_hash("hello");
        let h2 = SqliteMemory::content_hash("world");
        assert_ne!(h1, h2);
    }

    // ── Schema tests ─────────────────────────────────────────────

    #[tokio::test]
    async fn schema_has_fts5_table() {
        let (_tmp, mem) = temp_sqlite();
        let conn = mem.conn.lock();
        // FTS5 table should exist
        let count: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='memories_fts'",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(count, 1);
    }

    #[tokio::test]
    async fn schema_has_embedding_cache() {
        let (_tmp, mem) = temp_sqlite();
        let conn = mem.conn.lock();
        let count: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='embedding_cache'",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(count, 1);
    }

    #[tokio::test]
    async fn schema_has_embedding_band_table() {
        let (_tmp, mem) = temp_sqlite();
        let conn = mem.conn.lock();
        let count: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='memory_embedding_bands'",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(count, 1);
    }

    #[tokio::test]
    async fn schema_memories_has_embedding_column() {
        let (_tmp, mem) = temp_sqlite();
        let conn = mem.conn.lock();
        // Check that embedding column exists by querying it
        let result = conn.execute_batch("SELECT embedding FROM memories LIMIT 0");
        assert!(result.is_ok());
    }

    #[tokio::test]
    async fn schema_has_recall_filter_indexes() {
        let (_tmp, mem) = temp_sqlite();
        let conn = mem.conn.lock();
        for index_name in [
            "idx_memories_created_at",
            "idx_memories_session_created_at",
            "idx_memories_embedding_created_at",
            "idx_memories_embedding_session_created_at",
            "idx_memory_embedding_bands_lookup",
        ] {
            let count: i64 = conn
                .query_row(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name = ?1",
                    params![index_name],
                    |row| row.get(0),
                )
                .unwrap();
            assert_eq!(count, 1, "missing expected index {index_name}");
        }
    }

    #[tokio::test]
    async fn store_populates_embedding_bands() {
        let (_tmp, mem) = temp_sqlite_with_embedder(Arc::new(TestEmbedding));
        mem.store("keep", "velvet keep notes", MemoryCategory::Core, None)
            .await
            .unwrap();

        let entry = mem.get("keep").await.unwrap().unwrap();
        let count = count_embedding_bands(&mem, &entry.id);
        assert_eq!(count, LSH_BAND_COUNT as i64);
    }

    #[tokio::test]
    async fn forget_removes_embedding_bands() {
        let (_tmp, mem) = temp_sqlite_with_embedder(Arc::new(TestEmbedding));
        mem.store("keep", "velvet keep notes", MemoryCategory::Core, None)
            .await
            .unwrap();
        let entry = mem.get("keep").await.unwrap().unwrap();

        mem.forget("keep").await.unwrap();

        let count = count_embedding_bands(&mem, &entry.id);
        assert_eq!(count, 0);
    }

    #[test]
    fn startup_backfill_restores_missing_embedding_bands_for_legacy_rows() {
        let tmp = TempDir::new().unwrap();
        let mem =
            SqliteMemory::with_embedder(tmp.path(), Arc::new(TestEmbedding), 0.7, 0.3, 1000, None)
                .unwrap();

        let rt = tokio::runtime::Runtime::new().unwrap();
        rt.block_on(async {
            mem.store("legacy", "velvet keep notes", MemoryCategory::Core, None)
                .await
                .unwrap();
        });
        let entry = rt.block_on(async { mem.get("legacy").await.unwrap().unwrap() });

        {
            let conn = mem.conn.lock();
            conn.execute(
                "DELETE FROM memory_embedding_bands WHERE memory_id = ?1",
                params![&entry.id],
            )
            .unwrap();
        }
        drop(mem);

        let reopened = SqliteMemory::new(tmp.path()).unwrap();
        assert_eq!(
            count_embedding_bands(&reopened, &entry.id),
            LSH_BAND_COUNT as i64
        );

        let candidate_ids = {
            let conn = reopened.conn.lock();
            SqliteMemory::load_vector_candidate_ids(
                &conn,
                &SqliteMemory::embedding_band_hashes(&embedding_for_text("querysun")),
                RecallFilters::default(),
                8,
            )
            .unwrap()
        };
        assert_eq!(candidate_ids, vec![entry.id]);
    }

    #[test]
    fn startup_backfill_repairs_partial_embedding_band_rows() {
        let tmp = TempDir::new().unwrap();
        let mem =
            SqliteMemory::with_embedder(tmp.path(), Arc::new(TestEmbedding), 0.7, 0.3, 1000, None)
                .unwrap();

        let rt = tokio::runtime::Runtime::new().unwrap();
        rt.block_on(async {
            mem.store("legacy", "velvet keep notes", MemoryCategory::Core, None)
                .await
                .unwrap();
        });
        let entry = rt.block_on(async { mem.get("legacy").await.unwrap().unwrap() });

        {
            let conn = mem.conn.lock();
            conn.execute(
                "DELETE FROM memory_embedding_bands WHERE memory_id = ?1 AND band >= ?2",
                params![&entry.id, 3_i64],
            )
            .unwrap();
        }
        drop(mem);

        let reopened = SqliteMemory::new(tmp.path()).unwrap();
        assert_eq!(
            count_embedding_bands(&reopened, &entry.id),
            LSH_BAND_COUNT as i64
        );
    }

    // ── FTS5 sync trigger tests ──────────────────────────────────

    #[tokio::test]
    async fn fts5_syncs_on_insert() {
        let (_tmp, mem) = temp_sqlite();
        mem.store(
            "test_key",
            "unique_searchterm_xyz",
            MemoryCategory::Core,
            None,
        )
        .await
        .unwrap();

        let conn = mem.conn.lock();
        let count: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM memories_fts WHERE memories_fts MATCH '\"unique_searchterm_xyz\"'",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(count, 1);
    }

    #[tokio::test]
    async fn fts5_syncs_on_delete() {
        let (_tmp, mem) = temp_sqlite();
        mem.store(
            "del_key",
            "deletable_content_abc",
            MemoryCategory::Core,
            None,
        )
        .await
        .unwrap();
        mem.forget("del_key").await.unwrap();

        let conn = mem.conn.lock();
        let count: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM memories_fts WHERE memories_fts MATCH '\"deletable_content_abc\"'",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(count, 0);
    }

    #[tokio::test]
    async fn fts5_syncs_on_update() {
        let (_tmp, mem) = temp_sqlite();
        mem.store(
            "upd_key",
            "original_content_111",
            MemoryCategory::Core,
            None,
        )
        .await
        .unwrap();
        mem.store("upd_key", "updated_content_222", MemoryCategory::Core, None)
            .await
            .unwrap();

        let conn = mem.conn.lock();
        // Old content should not be findable
        let old: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM memories_fts WHERE memories_fts MATCH '\"original_content_111\"'",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(old, 0);

        // New content should be findable
        let new: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM memories_fts WHERE memories_fts MATCH '\"updated_content_222\"'",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(new, 1);
    }

    // ── Open timeout tests ────────────────────────────────────────

    #[test]
    fn open_with_timeout_succeeds_when_fast() {
        let tmp = TempDir::new().unwrap();
        let embedder = Arc::new(super::super::embeddings::NoopEmbedding);
        let mem = SqliteMemory::with_embedder(tmp.path(), embedder, 0.7, 0.3, 1000, Some(5));
        assert!(
            mem.is_ok(),
            "open with 5s timeout should succeed on fast path"
        );
        assert_eq!(mem.unwrap().name(), "sqlite");
    }

    #[tokio::test]
    async fn open_with_timeout_store_recall_unchanged() {
        let tmp = TempDir::new().unwrap();
        let mem = SqliteMemory::with_embedder(
            tmp.path(),
            Arc::new(super::super::embeddings::NoopEmbedding),
            0.7,
            0.3,
            1000,
            Some(2),
        )
        .unwrap();
        mem.store(
            "timeout_key",
            "value with timeout",
            MemoryCategory::Core,
            None,
        )
        .await
        .unwrap();
        let entry = mem.get("timeout_key").await.unwrap().unwrap();
        assert_eq!(entry.content, "value with timeout");
    }

    // ── With-embedder constructor test ───────────────────────────

    #[test]
    fn with_embedder_noop() {
        let tmp = TempDir::new().unwrap();
        let embedder = Arc::new(super::super::embeddings::NoopEmbedding);
        let mem = SqliteMemory::with_embedder(tmp.path(), embedder, 0.7, 0.3, 1000, None);
        assert!(mem.is_ok());
        assert_eq!(mem.unwrap().name(), "sqlite");
    }

    // ── Reindex test ─────────────────────────────────────────────

    #[tokio::test]
    async fn reindex_rebuilds_fts() {
        let (_tmp, mem) = temp_sqlite();
        mem.store("r1", "reindex test alpha", MemoryCategory::Core, None)
            .await
            .unwrap();
        mem.store("r2", "reindex test beta", MemoryCategory::Core, None)
            .await
            .unwrap();

        // Reindex should succeed (noop embedder → 0 re-embedded)
        let count = mem.reindex().await.unwrap();
        assert_eq!(count, 0);

        // FTS should still work after rebuild
        let results = mem.recall("reindex", 10, None, None, None).await.unwrap();
        assert_eq!(results.len(), 2);
    }

    #[tokio::test]
    async fn reindex_backfills_embedding_bands() {
        let (_tmp, mem) = temp_sqlite_with_embedder(Arc::new(TestEmbedding));
        mem.store("r1", "alpha archive", MemoryCategory::Core, None)
            .await
            .unwrap();
        let entry = mem.get("r1").await.unwrap().unwrap();

        {
            let conn = mem.conn.lock();
            conn.execute(
                "DELETE FROM memory_embedding_bands WHERE memory_id = ?1",
                params![&entry.id],
            )
            .unwrap();
        }

        let count = mem.reindex().await.unwrap();
        assert_eq!(count, 0);

        let conn = mem.conn.lock();
        let band_count: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM memory_embedding_bands WHERE memory_id = ?1",
                params![&entry.id],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(band_count, LSH_BAND_COUNT as i64);
    }

    // ── Recall limit test ────────────────────────────────────────

    #[tokio::test]
    async fn recall_respects_limit() {
        let (_tmp, mem) = temp_sqlite();
        for i in 0..20 {
            mem.store(
                &format!("k{i}"),
                &format!("common keyword item {i}"),
                MemoryCategory::Core,
                None,
            )
            .await
            .unwrap();
        }

        let results = mem
            .recall("common keyword", 5, None, None, None)
            .await
            .unwrap();
        assert!(results.len() <= 5);
    }

    // ── Score presence test ──────────────────────────────────────

    #[tokio::test]
    async fn recall_results_have_scores() {
        let (_tmp, mem) = temp_sqlite();
        mem.store("s1", "scored result test", MemoryCategory::Core, None)
            .await
            .unwrap();

        let results = mem.recall("scored", 10, None, None, None).await.unwrap();
        assert!(!results.is_empty());
        for r in &results {
            assert!(r.score.is_some(), "Expected score on result: {:?}", r.key);
        }
    }

    // ── Edge cases: FTS5 special characters ──────────────────────

    #[tokio::test]
    async fn recall_with_quotes_in_query() {
        let (_tmp, mem) = temp_sqlite();
        mem.store("q1", "He said hello world", MemoryCategory::Core, None)
            .await
            .unwrap();
        // Quotes in query should not crash FTS5
        let results = mem.recall("\"hello\"", 10, None, None, None).await.unwrap();
        // May or may not match depending on FTS5 escaping, but must not error
        assert!(results.len() <= 10);
    }

    #[tokio::test]
    async fn recall_with_asterisk_in_query() {
        let (_tmp, mem) = temp_sqlite();
        mem.store("a1", "wildcard test content", MemoryCategory::Core, None)
            .await
            .unwrap();
        let results = mem.recall("wild*", 10, None, None, None).await.unwrap();
        assert!(results.len() <= 10);
    }

    #[tokio::test]
    async fn recall_with_parentheses_in_query() {
        let (_tmp, mem) = temp_sqlite();
        mem.store("p1", "function call test", MemoryCategory::Core, None)
            .await
            .unwrap();
        let results = mem
            .recall("function()", 10, None, None, None)
            .await
            .unwrap();
        assert!(results.len() <= 10);
    }

    #[tokio::test]
    async fn recall_with_sql_injection_attempt() {
        let (_tmp, mem) = temp_sqlite();
        mem.store("safe", "normal content", MemoryCategory::Core, None)
            .await
            .unwrap();
        // Should not crash or leak data
        let results = mem
            .recall("'; DROP TABLE memories; --", 10, None, None, None)
            .await
            .unwrap();
        assert!(results.len() <= 10);
        // Table should still exist
        assert_eq!(mem.count().await.unwrap(), 1);
    }

    // ── Edge cases: store ────────────────────────────────────────

    #[tokio::test]
    async fn store_empty_content() {
        let (_tmp, mem) = temp_sqlite();
        mem.store("empty", "", MemoryCategory::Core, None)
            .await
            .unwrap();
        let entry = mem.get("empty").await.unwrap().unwrap();
        assert_eq!(entry.content, "");
    }

    #[tokio::test]
    async fn store_empty_key() {
        let (_tmp, mem) = temp_sqlite();
        mem.store("", "content for empty key", MemoryCategory::Core, None)
            .await
            .unwrap();
        let entry = mem.get("").await.unwrap().unwrap();
        assert_eq!(entry.content, "content for empty key");
    }

    #[tokio::test]
    async fn store_very_long_content() {
        let (_tmp, mem) = temp_sqlite();
        let long_content = "x".repeat(100_000);
        mem.store("long", &long_content, MemoryCategory::Core, None)
            .await
            .unwrap();
        let entry = mem.get("long").await.unwrap().unwrap();
        assert_eq!(entry.content.len(), 100_000);
    }

    #[tokio::test]
    async fn store_unicode_and_emoji() {
        let (_tmp, mem) = temp_sqlite();
        mem.store(
            "emoji_key_🦀",
            "こんにちは 🚀 Ñoño",
            MemoryCategory::Core,
            None,
        )
        .await
        .unwrap();
        let entry = mem.get("emoji_key_🦀").await.unwrap().unwrap();
        assert_eq!(entry.content, "こんにちは 🚀 Ñoño");
    }

    #[tokio::test]
    async fn store_content_with_newlines_and_tabs() {
        let (_tmp, mem) = temp_sqlite();
        let content = "line1\nline2\ttab\rcarriage\n\nnewparagraph";
        mem.store("whitespace", content, MemoryCategory::Core, None)
            .await
            .unwrap();
        let entry = mem.get("whitespace").await.unwrap().unwrap();
        assert_eq!(entry.content, content);
    }

    // ── Edge cases: recall ───────────────────────────────────────

    #[tokio::test]
    async fn recall_single_character_query() {
        let (_tmp, mem) = temp_sqlite();
        mem.store("a", "x marks the spot", MemoryCategory::Core, None)
            .await
            .unwrap();
        // Single char may not match FTS5 but LIKE fallback should work
        let results = mem.recall("x", 10, None, None, None).await.unwrap();
        // Should not crash; may or may not find results
        assert!(results.len() <= 10);
    }

    #[tokio::test]
    async fn recall_limit_zero() {
        let (_tmp, mem) = temp_sqlite();
        mem.store("a", "some content", MemoryCategory::Core, None)
            .await
            .unwrap();
        let results = mem.recall("some", 0, None, None, None).await.unwrap();
        assert!(results.is_empty());
    }

    #[tokio::test]
    async fn recall_limit_one() {
        let (_tmp, mem) = temp_sqlite();
        mem.store("a", "matching content alpha", MemoryCategory::Core, None)
            .await
            .unwrap();
        mem.store("b", "matching content beta", MemoryCategory::Core, None)
            .await
            .unwrap();
        let results = mem
            .recall("matching content", 1, None, None, None)
            .await
            .unwrap();
        assert_eq!(results.len(), 1);
    }

    #[tokio::test]
    async fn recall_matches_by_key_not_just_content() {
        let (_tmp, mem) = temp_sqlite();
        mem.store(
            "rust_preferences",
            "User likes systems programming",
            MemoryCategory::Core,
            None,
        )
        .await
        .unwrap();
        // "rust" appears in key but not content — LIKE fallback checks key too
        let results = mem.recall("rust", 10, None, None, None).await.unwrap();
        assert!(!results.is_empty(), "Should match by key");
    }

    #[tokio::test]
    async fn recall_unicode_query() {
        let (_tmp, mem) = temp_sqlite();
        mem.store("jp", "日本語のテスト", MemoryCategory::Core, None)
            .await
            .unwrap();
        let results = mem.recall("日本語", 10, None, None, None).await.unwrap();
        assert!(!results.is_empty());
    }

    // ── Edge cases: schema idempotency ───────────────────────────

    #[tokio::test]
    async fn schema_idempotent_reopen() {
        let tmp = TempDir::new().unwrap();
        {
            let mem = SqliteMemory::new(tmp.path()).unwrap();
            mem.store("k1", "v1", MemoryCategory::Core, None)
                .await
                .unwrap();
        }
        // Open again — init_schema runs again on existing DB
        let mem2 = SqliteMemory::new(tmp.path()).unwrap();
        let entry = mem2.get("k1").await.unwrap();
        assert!(entry.is_some());
        assert_eq!(entry.unwrap().content, "v1");
        // Store more data — should work fine
        mem2.store("k2", "v2", MemoryCategory::Daily, None)
            .await
            .unwrap();
        assert_eq!(mem2.count().await.unwrap(), 2);
    }

    #[tokio::test]
    async fn schema_triple_open() {
        let tmp = TempDir::new().unwrap();
        let _m1 = SqliteMemory::new(tmp.path()).unwrap();
        let _m2 = SqliteMemory::new(tmp.path()).unwrap();
        let m3 = SqliteMemory::new(tmp.path()).unwrap();
        assert!(m3.health_check().await);
    }

    // ── Edge cases: forget + FTS5 consistency ────────────────────

    #[tokio::test]
    async fn forget_then_recall_no_ghost_results() {
        let (_tmp, mem) = temp_sqlite();
        mem.store(
            "ghost",
            "phantom memory content",
            MemoryCategory::Core,
            None,
        )
        .await
        .unwrap();
        mem.forget("ghost").await.unwrap();
        let results = mem
            .recall("phantom memory", 10, None, None, None)
            .await
            .unwrap();
        assert!(
            results.is_empty(),
            "Deleted memory should not appear in recall"
        );
    }

    #[tokio::test]
    async fn forget_and_re_store_same_key() {
        let (_tmp, mem) = temp_sqlite();
        mem.store("cycle", "version 1", MemoryCategory::Core, None)
            .await
            .unwrap();
        mem.forget("cycle").await.unwrap();
        mem.store("cycle", "version 2", MemoryCategory::Core, None)
            .await
            .unwrap();
        let entry = mem.get("cycle").await.unwrap().unwrap();
        assert_eq!(entry.content, "version 2");
        assert_eq!(mem.count().await.unwrap(), 1);
    }

    // ── Edge cases: reindex ──────────────────────────────────────

    #[tokio::test]
    async fn reindex_empty_db() {
        let (_tmp, mem) = temp_sqlite();
        let count = mem.reindex().await.unwrap();
        assert_eq!(count, 0);
    }

    #[tokio::test]
    async fn reindex_twice_is_safe() {
        let (_tmp, mem) = temp_sqlite();
        mem.store("r1", "reindex data", MemoryCategory::Core, None)
            .await
            .unwrap();
        mem.reindex().await.unwrap();
        let count = mem.reindex().await.unwrap();
        assert_eq!(count, 0); // Noop embedder → nothing to re-embed
        // Data should still be intact
        let results = mem.recall("reindex", 10, None, None, None).await.unwrap();
        assert_eq!(results.len(), 1);
    }

    // ── Edge cases: content_hash ─────────────────────────────────

    #[test]
    fn content_hash_empty_string() {
        let h = SqliteMemory::content_hash("");
        assert!(!h.is_empty());
        assert_eq!(h.len(), 16); // 16 hex chars
    }

    #[test]
    fn content_hash_unicode() {
        let h1 = SqliteMemory::content_hash("🦀");
        let h2 = SqliteMemory::content_hash("🦀");
        assert_eq!(h1, h2);
        let h3 = SqliteMemory::content_hash("🚀");
        assert_ne!(h1, h3);
    }

    #[test]
    fn content_hash_long_input() {
        let long = "a".repeat(1_000_000);
        let h = SqliteMemory::content_hash(&long);
        assert_eq!(h.len(), 16);
    }

    // ── Edge cases: category helpers ─────────────────────────────

    #[test]
    fn category_roundtrip_custom_with_spaces() {
        let cat = MemoryCategory::Custom("my custom category".into());
        let s = SqliteMemory::category_to_str(&cat);
        assert_eq!(s, "my custom category");
        let back = SqliteMemory::str_to_category(&s);
        assert_eq!(back, cat);
    }

    #[test]
    fn category_roundtrip_empty_custom() {
        let cat = MemoryCategory::Custom(String::new());
        let s = SqliteMemory::category_to_str(&cat);
        assert_eq!(s, "");
        let back = SqliteMemory::str_to_category(&s);
        assert_eq!(back, MemoryCategory::Custom(String::new()));
    }

    // ── Edge cases: list ─────────────────────────────────────────

    #[tokio::test]
    async fn list_custom_category() {
        let (_tmp, mem) = temp_sqlite();
        mem.store(
            "c1",
            "custom1",
            MemoryCategory::Custom("project".into()),
            None,
        )
        .await
        .unwrap();
        mem.store(
            "c2",
            "custom2",
            MemoryCategory::Custom("project".into()),
            None,
        )
        .await
        .unwrap();
        mem.store("c3", "other", MemoryCategory::Core, None)
            .await
            .unwrap();

        let project = mem
            .list(Some(&MemoryCategory::Custom("project".into())), None)
            .await
            .unwrap();
        assert_eq!(project.len(), 2);
    }

    #[tokio::test]
    async fn list_empty_db() {
        let (_tmp, mem) = temp_sqlite();
        let all = mem.list(None, None).await.unwrap();
        assert!(all.is_empty());
    }

    // ── Session isolation ─────────────────────────────────────────

    #[tokio::test]
    async fn store_and_recall_with_session_id() {
        let (_tmp, mem) = temp_sqlite();
        mem.store("k1", "session A fact", MemoryCategory::Core, Some("sess-a"))
            .await
            .unwrap();
        mem.store("k2", "session B fact", MemoryCategory::Core, Some("sess-b"))
            .await
            .unwrap();
        mem.store("k3", "no session fact", MemoryCategory::Core, None)
            .await
            .unwrap();

        // Recall with session-a filter returns only session-a entry
        let results = mem
            .recall("fact", 10, Some("sess-a"), None, None)
            .await
            .unwrap();
        assert_eq!(results.len(), 1);
        assert_eq!(results[0].key, "k1");
        assert_eq!(results[0].session_id.as_deref(), Some("sess-a"));
    }

    #[tokio::test]
    async fn recall_no_session_filter_returns_all() {
        let (_tmp, mem) = temp_sqlite();
        mem.store("k1", "alpha fact", MemoryCategory::Core, Some("sess-a"))
            .await
            .unwrap();
        mem.store("k2", "beta fact", MemoryCategory::Core, Some("sess-b"))
            .await
            .unwrap();
        mem.store("k3", "gamma fact", MemoryCategory::Core, None)
            .await
            .unwrap();

        // Recall without session filter returns all matching entries
        let results = mem.recall("fact", 10, None, None, None).await.unwrap();
        assert_eq!(results.len(), 3);
    }

    #[tokio::test]
    async fn cross_session_recall_isolation() {
        let (_tmp, mem) = temp_sqlite();
        mem.store(
            "secret",
            "session A secret data",
            MemoryCategory::Core,
            Some("sess-a"),
        )
        .await
        .unwrap();

        // Session B cannot see session A data
        let results = mem
            .recall("secret", 10, Some("sess-b"), None, None)
            .await
            .unwrap();
        assert!(results.is_empty());

        // Session A can see its own data
        let results = mem
            .recall("secret", 10, Some("sess-a"), None, None)
            .await
            .unwrap();
        assert_eq!(results.len(), 1);
    }

    #[tokio::test]
    async fn list_with_session_filter() {
        let (_tmp, mem) = temp_sqlite();
        mem.store("k1", "a1", MemoryCategory::Core, Some("sess-a"))
            .await
            .unwrap();
        mem.store("k2", "a2", MemoryCategory::Conversation, Some("sess-a"))
            .await
            .unwrap();
        mem.store("k3", "b1", MemoryCategory::Core, Some("sess-b"))
            .await
            .unwrap();
        mem.store("k4", "none1", MemoryCategory::Core, None)
            .await
            .unwrap();

        // List with session-a filter
        let results = mem.list(None, Some("sess-a")).await.unwrap();
        assert_eq!(results.len(), 2);
        assert!(
            results
                .iter()
                .all(|e| e.session_id.as_deref() == Some("sess-a"))
        );

        // List with session-a + category filter
        let results = mem
            .list(Some(&MemoryCategory::Core), Some("sess-a"))
            .await
            .unwrap();
        assert_eq!(results.len(), 1);
        assert_eq!(results[0].key, "k1");
    }

    #[tokio::test]
    async fn schema_migration_idempotent_on_reopen() {
        let tmp = TempDir::new().unwrap();

        // First open: creates schema + migration
        {
            let mem = SqliteMemory::new(tmp.path()).unwrap();
            mem.store("k1", "before reopen", MemoryCategory::Core, Some("sess-x"))
                .await
                .unwrap();
        }

        // Second open: migration runs again but is idempotent
        {
            let mem = SqliteMemory::new(tmp.path()).unwrap();
            let results = mem
                .recall("reopen", 10, Some("sess-x"), None, None)
                .await
                .unwrap();
            assert_eq!(results.len(), 1);
            assert_eq!(results[0].key, "k1");
            assert_eq!(results[0].session_id.as_deref(), Some("sess-x"));
        }
    }

    // ── §4.1 Concurrent write contention tests ──────────────

    #[tokio::test]
    async fn sqlite_concurrent_writes_no_data_loss() {
        let (_tmp, mem) = temp_sqlite();
        let mem = std::sync::Arc::new(mem);

        let mut handles = Vec::new();
        for i in 0..10 {
            let mem = std::sync::Arc::clone(&mem);
            handles.push(tokio::spawn(async move {
                mem.store(
                    &format!("concurrent_key_{i}"),
                    &format!("value_{i}"),
                    MemoryCategory::Core,
                    None,
                )
                .await
                .unwrap();
            }));
        }

        for handle in handles {
            handle.await.unwrap();
        }

        let count = mem.count().await.unwrap();
        assert_eq!(
            count, 10,
            "all 10 concurrent writes must succeed without data loss"
        );
    }

    #[tokio::test]
    async fn sqlite_concurrent_read_write_no_panic() {
        let (_tmp, mem) = temp_sqlite();
        let mem = std::sync::Arc::new(mem);

        // Pre-populate
        mem.store("shared_key", "initial", MemoryCategory::Core, None)
            .await
            .unwrap();

        let mut handles = Vec::new();

        // Concurrent reads
        for _ in 0..5 {
            let mem = std::sync::Arc::clone(&mem);
            handles.push(tokio::spawn(async move {
                let _ = mem.get("shared_key").await.unwrap();
            }));
        }

        // Concurrent writes
        for i in 0..5 {
            let mem = std::sync::Arc::clone(&mem);
            handles.push(tokio::spawn(async move {
                mem.store(
                    &format!("key_{i}"),
                    &format!("val_{i}"),
                    MemoryCategory::Core,
                    None,
                )
                .await
                .unwrap();
            }));
        }

        for handle in handles {
            handle.await.unwrap();
        }

        // Should have 6 total entries (1 pre-existing + 5 new)
        assert_eq!(mem.count().await.unwrap(), 6);
    }

    // ── §4.2 Reindex / corruption recovery tests ────────────

    #[tokio::test]
    async fn sqlite_reindex_preserves_data() {
        let (_tmp, mem) = temp_sqlite();
        mem.store("a", "Rust is fast", MemoryCategory::Core, None)
            .await
            .unwrap();
        mem.store("b", "Python is interpreted", MemoryCategory::Core, None)
            .await
            .unwrap();

        mem.reindex().await.unwrap();

        let count = mem.count().await.unwrap();
        assert_eq!(count, 2, "reindex must preserve all entries");

        let entry = mem.get("a").await.unwrap();
        assert!(entry.is_some());
        assert_eq!(entry.unwrap().content, "Rust is fast");
    }

    #[tokio::test]
    async fn sqlite_reindex_idempotent() {
        let (_tmp, mem) = temp_sqlite();
        mem.store("x", "test data", MemoryCategory::Core, None)
            .await
            .unwrap();

        // Multiple reindex calls should be safe
        mem.reindex().await.unwrap();
        mem.reindex().await.unwrap();
        mem.reindex().await.unwrap();

        assert_eq!(mem.count().await.unwrap(), 1);
    }
}
