use crate::config::Config;
use crate::memory::knowledge_graph::{KnowledgeGraph, NodeType, Relation};
use crate::memory::sqlite::{MemoryRow, SqliteMemory};
use crate::memory::traits::{Memory, MemoryCategory};
use anyhow::Context;
use async_trait::async_trait;
use chrono::{DateTime, Duration as ChronoDuration, Utc};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::sync::Arc;
use tokio::io::{AsyncBufReadExt, AsyncRead, AsyncWrite, AsyncWriteExt, BufReader};
use tokio::process::Command;
use tokio::time::{Duration, sleep};
use uuid::Uuid;

pub const KAIROS_IDLE_SECS: u64 = 300;
pub const KAIROS_BATCH_LIMIT: usize = 64;
const KAIROS_POLL_INTERVAL_SECS: u64 = 60;
const KAIROS_COMPONENT_NAME: &str = "kairos";
const KAIROS_SOURCE_PROJECT: &str = "kairos";
#[cfg(windows)]
const KAIROS_TCP_PORT: u16 = 48765;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct DreamFact {
    pub entity: String,
    pub relationship: String,
    pub target: String,
    pub context: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KairosBatchRequest {
    pub request_id: String,
    pub rows: Vec<MemoryRow>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct KairosBatchResponse {
    pub source_ids: Vec<i64>,
    pub facts: Vec<DreamFact>,
}

#[async_trait]
pub trait IpcBridge: Send + Sync {
    async fn exchange(&self, request: &KairosBatchRequest) -> anyhow::Result<KairosBatchResponse>;
}

#[async_trait]
pub trait KairosSink: Send + Sync {
    async fn persist(
        &self,
        request: &KairosBatchRequest,
        response: &KairosBatchResponse,
    ) -> anyhow::Result<()>;
}

#[derive(Debug, Clone)]
pub struct KairosIdleState {
    pub latest_conversation_write_at: Option<DateTime<Utc>>,
}

impl KairosIdleState {
    pub fn from_latest_conversation_write_at(raw: Option<&str>) -> Option<Self> {
        let raw = raw?;
        let parsed = DateTime::parse_from_rfc3339(raw).ok()?;
        Some(Self {
            latest_conversation_write_at: Some(parsed.with_timezone(&Utc)),
        })
    }

    pub fn is_idle_at(&self, now: DateTime<Utc>, idle_for: Duration) -> bool {
        let Some(latest) = self.latest_conversation_write_at else {
            return false;
        };

        let Ok(threshold) = ChronoDuration::from_std(idle_for) else {
            return false;
        };

        now.signed_duration_since(latest) >= threshold
    }

    pub fn is_idle(&self, idle_for: Duration) -> bool {
        self.is_idle_at(Utc::now(), idle_for)
    }
}

pub struct KairosWorker<B, S> {
    sqlite: Arc<SqliteMemory>,
    bridge: B,
    sink: S,
    idle_for: Duration,
}

impl<B, S> KairosWorker<B, S>
where
    B: IpcBridge,
    S: KairosSink,
{
    pub fn new(sqlite: Arc<SqliteMemory>, bridge: B, sink: S) -> Self {
        Self {
            sqlite,
            bridge,
            sink,
            idle_for: Duration::from_secs(KAIROS_IDLE_SECS),
        }
    }

    pub fn new_for_tests(sqlite: Arc<SqliteMemory>, bridge: B, sink: S) -> Self {
        Self {
            sqlite,
            bridge,
            sink,
            idle_for: Duration::from_secs(0),
        }
    }

    pub async fn run_once(&self) -> anyhow::Result<()> {
        let latest_write = self.sqlite.latest_episodic_write_at().await?;
        let Some(idle_state) =
            KairosIdleState::from_latest_conversation_write_at(latest_write.as_deref())
        else {
            return Ok(());
        };

        if !idle_state.is_idle(self.idle_for) {
            tracing::debug!("kairos skipped: recent episodic write detected");
            return Ok(());
        }

        let rows = self.sqlite.fetch_unconsolidated(KAIROS_BATCH_LIMIT).await?;
        if rows.is_empty() {
            tracing::debug!("kairos skipped: no unconsolidated conversation rows");
            return Ok(());
        }

        let request = KairosBatchRequest {
            request_id: Uuid::new_v4().to_string(),
            rows,
        };
        let response = self.bridge.exchange(&request).await?;

        anyhow::ensure!(
            !response.source_ids.is_empty(),
            "kairos response must include source_ids for non-empty batches"
        );

        self.sink.persist(&request, &response).await?;
        self.sqlite
            .mark_as_consolidated(&response.source_ids)
            .await?;
        Ok(())
    }
}

#[derive(Clone)]
pub enum KairosSinkImpl {
    MemoryThenGraph {
        memory: Arc<dyn Memory>,
        graph: Arc<KnowledgeGraph>,
    },
    KnowledgeGraph {
        graph: Arc<KnowledgeGraph>,
    },
}

impl KairosSinkImpl {
    pub fn mem0_then_graph(memory: Arc<dyn Memory>, graph: Arc<KnowledgeGraph>) -> Self {
        Self::MemoryThenGraph { memory, graph }
    }

    pub fn knowledge_graph(graph: Arc<KnowledgeGraph>) -> Self {
        Self::KnowledgeGraph { graph }
    }
}

#[async_trait]
impl KairosSink for KairosSinkImpl {
    async fn persist(
        &self,
        request: &KairosBatchRequest,
        response: &KairosBatchResponse,
    ) -> anyhow::Result<()> {
        match self {
            Self::MemoryThenGraph { memory, graph } => {
                if persist_to_memory(memory.as_ref(), request, response)
                    .await
                    .is_ok()
                {
                    return Ok(());
                }

                tracing::warn!("kairos mem0 sink failed; falling back to local knowledge graph");
                persist_to_graph(graph, request, response)
            }
            Self::KnowledgeGraph { graph } => persist_to_graph(graph, request, response),
        }
    }
}

pub async fn build_default_sink(
    config: &Config,
    active_memory: Arc<dyn Memory>,
) -> anyhow::Result<KairosSinkImpl> {
    let graph = Arc::new(KnowledgeGraph::new(
        &expand_path(&config.knowledge.db_path),
        config.knowledge.max_nodes,
    )?);

    if active_memory.name() == "mem0" && active_memory.health_check().await {
        Ok(KairosSinkImpl::mem0_then_graph(active_memory, graph))
    } else {
        Ok(KairosSinkImpl::knowledge_graph(graph))
    }
}

#[allow(clippy::used_underscore_binding, unused_variables)]
pub fn build_default_bridge(_config: &Config) -> anyhow::Result<Box<dyn IpcBridge>> {
    #[cfg(unix)]
    {
        Ok(Box::new(UnixIpcBridge::new(
            _config.workspace_dir.join("kairos.sock"),
        )))
    }

    #[cfg(windows)]
    {
        let addr = format!("127.0.0.1:{KAIROS_TCP_PORT}").parse()?;
        Ok(Box::new(TcpIpcBridge::new(addr)))
    }
}

/// Spawn the Python dreamer service as a background task.
/// On Windows connects to TCP 48765; on Unix uses a Unix domain socket.
/// Returns immediately — the process continues independently.
fn spawn_dreamer() {
    // Derive the script path relative to the running binary.
    // binary:  .../james_library/target/debug/rain[.exe]
    // script:  .../james_library/src/service/kairos_dreamer.py
    let script_path: Option<PathBuf> = {
        let exe = std::env::current_exe().ok();
        exe.map(|e| {
            let base = e
                .parent() // target/debug
                .and_then(|p| p.parent()) // target
                .and_then(|p| p.parent()) // project root
                .unwrap_or(&e);
            base.join("src").join("service").join("kairos_dreamer.py")
        })
    };

    let Some(script_path) = script_path else {
        tracing::warn!("KAIROS dreamer: could not determine executable path");
        return;
    };

    if !script_path.exists() {
        tracing::warn!(
            "KAIROS dreamer script not found at {}",
            script_path.display()
        );
        return;
    }

    // Use python3 on Unix, python on Windows
    #[cfg(windows)]
    let python = "python";
    #[cfg(not(windows))]
    let python = "python3";

    let mut child = match Command::new(python)
        .arg(&script_path)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
    {
        Ok(c) => c,
        Err(e) => {
            tracing::warn!("KAIROS dreamer: failed to spawn: {}", e);
            return;
        }
    };

    let pid = child.id();
    tracing::info!(
        "KAIROS dreamer spawned (pid {pid:?}), script: {}",
        script_path.display()
    );

    // Log stdout/stderr in background so we don't block
    let stdout = child.stdout.take();
    let stderr = child.stderr.take();

    if let Some(stdout) = stdout {
        tokio::spawn(async move {
            let mut r = BufReader::new(stdout);
            let mut line = String::new();
            while r.read_line(&mut line).await.unwrap_or(0) > 0 {
                tracing::info!("[kairos-dreamer] {}", line.trim());
                line.clear();
            }
        });
    }
    if let Some(stderr) = stderr {
        tokio::spawn(async move {
            let mut r = BufReader::new(stderr);
            let mut line = String::new();
            while r.read_line(&mut line).await.unwrap_or(0) > 0 {
                tracing::warn!("[kairos-dreamer] {}", line.trim());
                line.clear();
            }
        });
    }

    // tokio::process::Child is dropped here — the actual process keeps running
    // independently. Daemon shutdown (SIGINT/SIGTERM) cascades to the child.
    let _ = pid;
}

pub async fn run(config: Config) -> anyhow::Result<()> {
    crate::health::mark_component_ok(KAIROS_COMPONENT_NAME);

    let sqlite = Arc::new(SqliteMemory::new(&config.workspace_dir)?);
    let active_memory: Arc<dyn Memory> =
        Arc::from(crate::memory::create_memory_with_storage_and_routes(
            &config.memory,
            &config.embedding_routes,
            Some(&config.storage.provider.config),
            &config.workspace_dir,
            config.api_key.as_deref(),
        )?);

    let bridge = build_default_bridge(&config)?;
    let sink = build_default_sink(&config, Arc::clone(&active_memory)).await?;
    let worker = KairosWorker::new(sqlite, bridge, sink);

    // Spawn the Python dreamer service as a background process
    spawn_dreamer();

    tracing::info!("KAIROS daemon started");

    loop {
        match worker.run_once().await {
            Ok(()) => {
                crate::health::mark_component_ok(KAIROS_COMPONENT_NAME);
            }
            Err(err) => {
                crate::health::mark_component_error(KAIROS_COMPONENT_NAME, err.to_string());
                tracing::warn!("KAIROS cycle failed: {err}");
            }
        }

        sleep(Duration::from_secs(KAIROS_POLL_INTERVAL_SECS)).await;
    }
}

#[cfg(unix)]
#[derive(Debug, Clone)]
pub struct UnixIpcBridge {
    pub socket_path: PathBuf,
}

#[cfg(unix)]
impl UnixIpcBridge {
    pub fn new(socket_path: PathBuf) -> Self {
        Self { socket_path }
    }
}

#[cfg(unix)]
#[async_trait]
impl IpcBridge for UnixIpcBridge {
    async fn exchange(&self, request: &KairosBatchRequest) -> anyhow::Result<KairosBatchResponse> {
        let stream = tokio::net::UnixStream::connect(&self.socket_path)
            .await
            .with_context(|| format!("failed to connect to {:?}", self.socket_path))?;
        exchange_json_stream(stream, request).await
    }
}

#[async_trait]
impl<T> IpcBridge for Box<T>
where
    T: IpcBridge + ?Sized,
{
    async fn exchange(&self, request: &KairosBatchRequest) -> anyhow::Result<KairosBatchResponse> {
        (**self).exchange(request).await
    }
}

#[cfg(windows)]
#[derive(Debug, Clone)]
pub struct TcpIpcBridge {
    pub bind_addr: std::net::SocketAddr,
}

#[cfg(windows)]
impl TcpIpcBridge {
    pub fn new(bind_addr: std::net::SocketAddr) -> Self {
        Self { bind_addr }
    }
}

#[cfg(windows)]
#[async_trait]
impl IpcBridge for TcpIpcBridge {
    async fn exchange(&self, request: &KairosBatchRequest) -> anyhow::Result<KairosBatchResponse> {
        let stream = tokio::net::TcpStream::connect(self.bind_addr)
            .await
            .with_context(|| format!("failed to connect to {}", self.bind_addr))?;
        exchange_json_stream(stream, request).await
    }
}

async fn exchange_json_stream<S>(
    mut stream: S,
    request: &KairosBatchRequest,
) -> anyhow::Result<KairosBatchResponse>
where
    S: AsyncRead + AsyncWrite + Unpin,
{
    let request_json = serde_json::to_string(request)?;
    stream.write_all(request_json.as_bytes()).await?;
    stream.write_all(b"\n").await?;
    stream.flush().await?;

    let mut reader = BufReader::new(stream);
    let mut line = String::new();
    let bytes = reader.read_line(&mut line).await?;
    anyhow::ensure!(
        bytes > 0,
        "kairos bridge closed before returning a response"
    );
    let response: KairosBatchResponse = serde_json::from_str(line.trim())?;
    Ok(response)
}

fn expand_path(path: &str) -> PathBuf {
    PathBuf::from(shellexpand::tilde(path).into_owned())
}

fn fact_payload_string(
    request: &KairosBatchRequest,
    response: &KairosBatchResponse,
    fact: &DreamFact,
) -> String {
    serde_json::json!({
        "request_id": request.request_id,
        "source_ids": response.source_ids,
        "entity": fact.entity,
        "relationship": fact.relationship,
        "target": fact.target,
        "context": fact.context,
    })
    .to_string()
}

fn fact_memory_key(response: &KairosBatchResponse, fact: &DreamFact) -> String {
    use sha2::{Digest, Sha256};

    let mut hasher = Sha256::new();
    for source_id in &response.source_ids {
        hasher.update(source_id.to_be_bytes());
    }
    hasher.update(fact.entity.trim().as_bytes());
    hasher.update(fact.relationship.trim().as_bytes());
    hasher.update(fact.target.trim().as_bytes());
    hasher.update(fact.context.trim().as_bytes());

    let digest = hasher.finalize();
    let fingerprint = hex::encode(&digest[..8]);
    format!("kairos:{fingerprint}")
}

fn normalize_component(value: &str) -> String {
    let mut out = String::new();
    let mut previous_separator = false;

    for ch in value.trim().chars() {
        if ch.is_ascii_alphanumeric() {
            out.push(ch.to_ascii_lowercase());
            previous_separator = false;
        } else if !previous_separator {
            out.push('_');
            previous_separator = true;
        }
    }

    let trimmed = out.trim_matches('_').to_string();
    if trimmed.is_empty() {
        "item".to_string()
    } else {
        trimmed
    }
}

fn normalize_relation(value: &str) -> (Relation, Option<String>) {
    let trimmed = value.trim();
    let lowered = trimmed.to_ascii_lowercase();
    let relation = Relation::parse(trimmed).unwrap_or(Relation::AppliesTo);
    let supported = matches!(
        lowered.as_str(),
        "uses" | "replaces" | "extends" | "authored_by" | "applies_to"
    );

    if supported {
        (relation, None)
    } else {
        (Relation::AppliesTo, Some(trimmed.to_string()))
    }
}

fn graph_tags(fact: &DreamFact, relation: &Relation, raw_relation: Option<&str>) -> Vec<String> {
    let mut tags = vec![
        KAIROS_SOURCE_PROJECT.to_string(),
        format!("relation:{}", relation.as_str()),
        format!("entity:{}", normalize_component(&fact.entity)),
        format!("target:{}", normalize_component(&fact.target)),
    ];

    if let Some(raw_relation) = raw_relation {
        tags.push(format!(
            "raw_relation:{}",
            normalize_component(raw_relation)
        ));
    }

    tags
}

fn graph_node_title(value: &str, fallback: &str) -> String {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        fallback.to_string()
    } else {
        trimmed.to_string()
    }
}

async fn persist_to_memory(
    memory: &dyn Memory,
    request: &KairosBatchRequest,
    response: &KairosBatchResponse,
) -> anyhow::Result<()> {
    for (idx, fact) in response.facts.iter().enumerate() {
        let key = format!("{}:{idx}", fact_memory_key(response, fact));
        let content = fact_payload_string(request, response, fact);
        memory
            .store(&key, &content, MemoryCategory::Core, None)
            .await
            .with_context(|| format!("mem0 store failed for fact #{idx}"))?;
    }

    Ok(())
}

fn persist_to_graph(
    graph: &KnowledgeGraph,
    request: &KairosBatchRequest,
    response: &KairosBatchResponse,
) -> anyhow::Result<()> {
    for fact in &response.facts {
        let content = fact_payload_string(request, response, fact);
        let (relation, raw_relation) = normalize_relation(&fact.relationship);
        let tags = graph_tags(fact, &relation, raw_relation.as_deref());
        let entity_title = graph_node_title(&fact.entity, "entity");
        let target_title = graph_node_title(&fact.target, "target");

        let source_id = graph.add_node(
            NodeType::Pattern,
            &entity_title,
            &content,
            &tags,
            Some(KAIROS_SOURCE_PROJECT),
        )?;
        let target_id = graph.add_node(
            NodeType::Pattern,
            &target_title,
            &content,
            &tags,
            Some(KAIROS_SOURCE_PROJECT),
        )?;
        graph.add_edge(&source_id, &target_id, relation)?;
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::memory::traits::{Memory, MemoryCategory, MemoryEntry};
    use anyhow::anyhow;
    use std::sync::Mutex;
    use tempfile::TempDir;
    #[cfg(unix)]
    use tokio::net::UnixListener;

    fn temp_sqlite() -> (TempDir, Arc<SqliteMemory>) {
        let tmp = TempDir::new().unwrap();
        let mem = Arc::new(SqliteMemory::new(tmp.path()).unwrap());
        (tmp, mem)
    }

    fn sample_fact() -> DreamFact {
        DreamFact {
            entity: "User".into(),
            relationship: "applies_to".into(),
            target: "Rust".into(),
            context: "User likes Rust".into(),
        }
    }

    struct FakeBridge {
        response: KairosBatchResponse,
    }

    #[async_trait]
    impl IpcBridge for FakeBridge {
        async fn exchange(
            &self,
            _request: &KairosBatchRequest,
        ) -> anyhow::Result<KairosBatchResponse> {
            Ok(self.response.clone())
        }
    }

    struct ToggleSink {
        failures_remaining: Mutex<usize>,
    }

    impl ToggleSink {
        fn fail_once() -> Self {
            Self {
                failures_remaining: Mutex::new(1),
            }
        }
    }

    #[async_trait]
    impl KairosSink for ToggleSink {
        async fn persist(
            &self,
            _request: &KairosBatchRequest,
            _response: &KairosBatchResponse,
        ) -> anyhow::Result<()> {
            let mut guard = self.failures_remaining.lock().unwrap();
            if *guard > 0 {
                *guard -= 1;
                anyhow::bail!("sink failure");
            }
            Ok(())
        }
    }

    struct FailingMem0Memory;

    #[async_trait]
    impl Memory for FailingMem0Memory {
        fn name(&self) -> &str {
            "mem0"
        }

        async fn store(
            &self,
            _key: &str,
            _content: &str,
            _category: MemoryCategory,
            _session_id: Option<&str>,
        ) -> anyhow::Result<()> {
            anyhow::bail!("mem0 unavailable");
        }

        async fn recall(
            &self,
            _query: &str,
            _limit: usize,
            _session_id: Option<&str>,
            _since: Option<&str>,
            _until: Option<&str>,
        ) -> anyhow::Result<Vec<MemoryEntry>> {
            Err(anyhow!("not used in tests"))
        }

        async fn get(&self, _key: &str) -> anyhow::Result<Option<MemoryEntry>> {
            Ok(None)
        }

        async fn list(
            &self,
            _category: Option<&MemoryCategory>,
            _session_id: Option<&str>,
        ) -> anyhow::Result<Vec<MemoryEntry>> {
            Ok(Vec::new())
        }

        async fn forget(&self, _key: &str) -> anyhow::Result<bool> {
            Ok(false)
        }

        async fn count(&self) -> anyhow::Result<usize> {
            Ok(0)
        }

        async fn health_check(&self) -> bool {
            true
        }
    }

    #[tokio::test]
    async fn run_once_marks_rows_only_after_sink_success() {
        let (_tmp, mem) = temp_sqlite();
        mem.store(
            "conv-1",
            "User likes Rust",
            MemoryCategory::Conversation,
            Some("sess-a"),
        )
        .await
        .unwrap();

        let rows = mem.fetch_unconsolidated(10).await.unwrap();
        let bridge = FakeBridge {
            response: KairosBatchResponse {
                source_ids: vec![rows[0].id],
                facts: vec![sample_fact()],
            },
        };
        let sink = ToggleSink::fail_once();
        let worker = KairosWorker::new_for_tests(Arc::clone(&mem), bridge, sink);

        assert!(worker.run_once().await.is_err());
        assert_eq!(mem.fetch_unconsolidated(10).await.unwrap().len(), 1);

        worker.run_once().await.unwrap();
        assert!(mem.fetch_unconsolidated(10).await.unwrap().is_empty());
    }

    #[tokio::test]
    async fn run_once_falls_back_to_local_graph_when_mem0_sink_fails() {
        let (_tmp, mem) = temp_sqlite();
        mem.store(
            "conv-1",
            "Python complements Rust",
            MemoryCategory::Conversation,
            None,
        )
        .await
        .unwrap();

        let rows = mem.fetch_unconsolidated(10).await.unwrap();
        let bridge = FakeBridge {
            response: KairosBatchResponse {
                source_ids: vec![rows[0].id],
                facts: vec![DreamFact {
                    entity: "Python".into(),
                    relationship: "uses".into(),
                    target: "Rust".into(),
                    context: "Python complements Rust".into(),
                }],
            },
        };
        let graph_dir = TempDir::new().unwrap();
        let graph =
            Arc::new(KnowledgeGraph::new(&graph_dir.path().join("knowledge.db"), 1000).unwrap());
        let sink = KairosSinkImpl::mem0_then_graph(Arc::new(FailingMem0Memory), Arc::clone(&graph));
        let worker = KairosWorker::new_for_tests(Arc::clone(&mem), bridge, sink);

        worker.run_once().await.unwrap();
        assert!(mem.fetch_unconsolidated(10).await.unwrap().is_empty());
        assert!(graph.stats().unwrap().total_nodes >= 2);
        assert!(graph.stats().unwrap().total_edges >= 1);
    }

    #[test]
    fn idle_check_requires_five_minutes_since_latest_conversation_write() {
        let now = Utc::now();
        let recent = KairosIdleState {
            latest_conversation_write_at: Some(now - ChronoDuration::seconds(299)),
        };
        let stale = KairosIdleState {
            latest_conversation_write_at: Some(now - ChronoDuration::seconds(300)),
        };

        assert!(!recent.is_idle_at(now, Duration::from_secs(KAIROS_IDLE_SECS)));
        assert!(stale.is_idle_at(now, Duration::from_secs(KAIROS_IDLE_SECS)));
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn unix_bridge_roundtrip_reads_and_writes_one_json_line() {
        let tmp = TempDir::new().unwrap();
        let socket_path = tmp.path().join("kairos.sock");
        let listener = UnixListener::bind(&socket_path).unwrap();
        let expected_response = KairosBatchResponse {
            source_ids: vec![7],
            facts: vec![DreamFact {
                entity: "Rust".into(),
                relationship: "uses".into(),
                target: "Tokio".into(),
                context: "Rust uses Tokio".into(),
            }],
        };

        let server = tokio::spawn({
            let expected_response = expected_response.clone();
            async move {
                let (stream, _) = listener.accept().await.unwrap();
                let mut reader = BufReader::new(stream);
                let mut line = String::new();
                reader.read_line(&mut line).await.unwrap();
                let request: KairosBatchRequest = serde_json::from_str(line.trim()).unwrap();
                assert!(!request.request_id.is_empty());

                let mut stream = reader.into_inner();
                let response = serde_json::to_string(&expected_response).unwrap();
                stream.write_all(response.as_bytes()).await.unwrap();
                stream.write_all(b"\n").await.unwrap();
                stream.flush().await.unwrap();
            }
        });

        let bridge = UnixIpcBridge::new(socket_path);
        let request = KairosBatchRequest {
            request_id: "req-1".into(),
            rows: Vec::new(),
        };
        let response = bridge.exchange(&request).await.unwrap();
        assert_eq!(response, expected_response);
        server.await.unwrap();
    }
}
