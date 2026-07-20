//! Episodic memory data contracts and the JSONL event stream.
//!
//! Canonical schema for `episodic_memory/episodic_events.jsonl` (raw events,
//! written by Rust) and `episodic_memory/episodes.jsonl` (segmented episodes,
//! written by the Python ingestor). The Python mirror lives in
//! `rain_contracts/episodic.py`; both sides follow the same compatibility
//! contract:
//!
//! - v2 only **adds optional fields** to the v1 line schema, so v1 readers
//!   and writers keep working.
//! - Unknown keys are ignored on read; missing optional keys default to
//!   `None`. Bump `EPISODIC_SCHEMA_VERSION` only when a required field
//!   changes meaning.
//! - Single writer per file: Rust appends events, Python appends episodes.

use super::state::BehavioralState;
use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

pub const EPISODIC_SCHEMA_VERSION: u32 = 2;

/// How an event concluded.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum EventOutcome {
    Success,
    Failure,
    /// The vitals monitor intervened (redirect/yield/alert).
    Intervened,
}

fn empty_args() -> serde_json::Value {
    serde_json::Value::Object(serde_json::Map::new())
}

/// One raw episodic event (one JSONL line).
///
/// The first six fields are the v1 wire schema consumed by
/// `episodic_memory_ingestor.py`; everything else is an optional v2
/// addition.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EpisodicEventV2 {
    // ── v1 fields (wire-required) ───────────────────────────────
    /// RFC 3339 timestamp.
    pub timestamp: String,
    /// R.A.I.N.-scoped actor label only (never a real identity).
    pub agent_name: String,
    pub tool: String,
    /// Tool arguments. Writers should keep this empty or redacted: raw
    /// arguments can carry sensitive payloads and this file is plaintext.
    #[serde(default = "empty_args")]
    pub args: serde_json::Value,
    /// One-line natural-language rendering for graph ingestion.
    pub sentence: String,
    pub duration_ms: u64,
    // ── v2 additions (all optional ⇒ v1 lines still parse) ─────
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub schema_version: Option<u32>,
    /// Assigned by the Python segmenter, not the event writer.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub episode_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub session_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub channel: Option<String>,
    /// Behavioral state at event time.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub state: Option<BehavioralState>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub outcome: Option<EventOutcome>,
}

impl EpisodicEventV2 {
    pub fn to_jsonl(&self) -> Result<String> {
        serde_json::to_string(self).context("serialize episodic event")
    }

    /// Parse one JSONL line. Tolerates v1 lines (no v2 fields) and lines
    /// from future writers (unknown keys ignored).
    pub fn from_jsonl(line: &str) -> Result<Self> {
        serde_json::from_str(line.trim()).context("parse episodic event line")
    }
}

/// Behavioral/affect trace for alignment retrieval.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct AffectTrace {
    /// −1.0 (failing/frustrated) … +1.0 (succeeding/aligned).
    pub valence: f64,
    /// 0.0 (calm/idle) … 1.0 (alert/remediating).
    pub arousal: f64,
    #[serde(default)]
    pub tags: Vec<String>,
}

/// A segmented episode (one line of `episodes.jsonl`), written by the
/// Python ingestor and read back by Rust for boot-time recall.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Episode {
    pub schema_version: u32,
    /// `"ep-..."` identifier.
    pub id: String,
    pub started_at: String,
    pub ended_at: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub session_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub channel: Option<String>,
    pub event_count: u32,
    /// Narrative summary indexed into the vector store.
    pub summary: String,
    #[serde(default)]
    pub affect: AffectTrace,
    /// 0.0–1.0; maps onto `MemoryEntry.importance` for ranking and decay.
    pub salience: f64,
    /// States visited in order with durations in milliseconds.
    #[serde(default)]
    pub state_trace: Vec<(BehavioralState, u64)>,
    /// Ambient facts promoted at episode close (provenance-tagged).
    #[serde(default)]
    pub ambient_digest: Vec<String>,
    /// Vitals interventions that occurred during the episode.
    #[serde(default)]
    pub interventions: Vec<String>,
}

impl Episode {
    pub fn from_jsonl(line: &str) -> Result<Self> {
        serde_json::from_str(line.trim()).context("parse episode line")
    }
}

/// Raw event stream path (single writer: Rust).
pub fn episodic_events_path(workspace_dir: &Path) -> PathBuf {
    workspace_dir
        .join("episodic_memory")
        .join("episodic_events.jsonl")
}

/// Segmented episodes path (single writer: Python ingestor).
pub fn episodes_path(workspace_dir: &Path) -> PathBuf {
    workspace_dir.join("episodic_memory").join("episodes.jsonl")
}

/// Append one event to the workspace event stream, creating the directory
/// on first use. Line-atomic appends keep the stream tail-safe for the
/// Python reader.
pub async fn append_event(workspace_dir: &Path, event: &EpisodicEventV2) -> Result<()> {
    let path = episodic_events_path(workspace_dir);
    if let Some(parent) = path.parent() {
        tokio::fs::create_dir_all(parent)
            .await
            .context("create episodic_memory directory")?;
    }
    let mut line = event.to_jsonl()?;
    line.push('\n');
    use tokio::io::AsyncWriteExt;
    let mut file = tokio::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&path)
        .await
        .context("open episodic event stream")?;
    file.write_all(line.as_bytes())
        .await
        .context("append episodic event")?;
    // tokio::fs::File buffers writes onto a background blocking task; write_all
    // can return before the bytes reach the OS, and dropping the handle does
    // not wait for them. Flush explicitly so a following read (or a fast
    // shutdown) always observes the appended line.
    file.flush().await.context("flush episodic event")?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn v2_event() -> EpisodicEventV2 {
        EpisodicEventV2 {
            timestamp: "2026-06-09T12:00:00Z".into(),
            agent_name: "R.A.I.N.Agent".into(),
            tool: "file_read".into(),
            args: empty_args(),
            sentence: "R.A.I.N.Agent ran tool 'file_read' (success, 12 ms)".into(),
            duration_ms: 12,
            schema_version: Some(EPISODIC_SCHEMA_VERSION),
            episode_id: None,
            session_id: Some("session-1".into()),
            channel: Some("telegram".into()),
            state: Some(BehavioralState::Thinking),
            outcome: Some(EventOutcome::Success),
        }
    }

    #[test]
    fn v2_event_round_trips() {
        let line = v2_event().to_jsonl().unwrap();
        let parsed = EpisodicEventV2::from_jsonl(&line).unwrap();
        assert_eq!(parsed.tool, "file_read");
        assert_eq!(parsed.state, Some(BehavioralState::Thinking));
        assert_eq!(parsed.outcome, Some(EventOutcome::Success));
        assert_eq!(parsed.schema_version, Some(2));
    }

    #[test]
    fn v1_line_without_v2_fields_parses() {
        // Exactly what the pre-v2 writer emitted.
        let line = r#"{"timestamp":"2026-06-09T12:00:00Z","agent_name":"R.A.I.N.Agent","tool":"shell","args":{"cmd":"ls"},"sentence":"ran shell","duration_ms":40}"#;
        let parsed = EpisodicEventV2::from_jsonl(line).unwrap();
        assert_eq!(parsed.tool, "shell");
        assert!(parsed.schema_version.is_none());
        assert!(parsed.state.is_none());
        assert!(parsed.outcome.is_none());
    }

    #[test]
    fn unknown_keys_from_future_writers_are_ignored() {
        let line = r#"{"timestamp":"t","agent_name":"R.A.I.N.Agent","tool":"x","args":{},"sentence":"s","duration_ms":1,"some_v3_field":true}"#;
        let parsed = EpisodicEventV2::from_jsonl(line).unwrap();
        assert_eq!(parsed.tool, "x");
    }

    #[test]
    fn v2_serialization_omits_absent_optionals() {
        let mut event = v2_event();
        event.session_id = None;
        event.channel = None;
        event.state = None;
        event.outcome = None;
        let line = event.to_jsonl().unwrap();
        assert!(!line.contains("session_id"));
        assert!(!line.contains("\"state\""));
        assert!(!line.contains("episode_id"));
    }

    #[test]
    fn episode_parses_python_written_line() {
        // Mirrors rain_contracts.episodic.Episode.to_jsonl output, including
        // the state_trace pair encoding.
        let line = r#"{"schema_version":2,"id":"ep-01","started_at":"2026-06-09T12:00:00Z","ended_at":"2026-06-09T12:10:00Z","session_id":"session-1","channel":"telegram","event_count":4,"summary":"4 events using file_read, shell.","affect":{"valence":0.5,"arousal":0.0,"tags":["productive"]},"salience":0.4,"state_trace":[["thinking",60000],["idle",540000]],"ambient_digest":[],"interventions":[]}"#;
        let episode = Episode::from_jsonl(line).unwrap();
        assert_eq!(episode.event_count, 4);
        assert_eq!(episode.state_trace[0], (BehavioralState::Thinking, 60000));
        assert!((episode.affect.valence - 0.5).abs() < f64::EPSILON);
    }

    #[tokio::test]
    async fn append_event_creates_stream_and_appends_lines() {
        let dir = tempfile::tempdir().unwrap();
        append_event(dir.path(), &v2_event()).await.unwrap();
        append_event(dir.path(), &v2_event()).await.unwrap();

        let content = tokio::fs::read_to_string(episodic_events_path(dir.path()))
            .await
            .unwrap();
        let lines: Vec<&str> = content.lines().collect();
        assert_eq!(lines.len(), 2);
        for line in lines {
            EpisodicEventV2::from_jsonl(line).unwrap();
        }
    }
}
