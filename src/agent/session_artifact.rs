use crate::memory::MemoryEntry;
use anyhow::Result;
use chrono::Utc;
use serde::Serialize;
use std::fs;
use std::path::{Path, PathBuf};
use uuid::Uuid;

const SCHEMA_VERSION: &str = "rain-session-artifact/v1";

#[derive(Serialize)]
struct Evidence {
    source: String,
    quote: String,
    span_start: Option<usize>,
    span_end: Option<usize>,
}

#[derive(Serialize)]
struct GroundedResponse {
    answer: String,
    confidence: f64,
    provenance: Vec<String>,
    evidence: Vec<Evidence>,
    repro_steps: Vec<String>,
    grounded: bool,
    red_badge: bool,
}

#[derive(Serialize)]
struct TurnMetadata {
    verified_count: usize,
    unverified_count: usize,
    citation_rate: f64,
}

#[derive(Serialize)]
struct TurnRecord {
    index: usize,
    timestamp: String,
    agent: String,
    content: String,
    metadata: TurnMetadata,
    grounded_response: GroundedResponse,
}

#[derive(Serialize)]
struct SessionArtifact {
    schema_version: String,
    session_id: String,
    status: String,
    topic: String,
    model: String,
    recursive_depth: usize,
    started_at: String,
    completed_at: String,
    library_path: String,
    log_path: String,
    loaded_papers_count: usize,
    loaded_papers: Vec<String>,
    metrics: serde_json::Value,
    summary: String,
    turns: Vec<TurnRecord>,
}

fn now_iso() -> String {
    Utc::now().to_rfc3339()
}

fn artifact_dir(workspace_dir: &Path) -> PathBuf {
    workspace_dir
        .join("meeting_archives")
        .join("session_artifacts")
}

fn build_grounded_response(
    answer: &str,
    workspace_dir: &Path,
    evidence_entries: &[MemoryEntry],
) -> GroundedResponse {
    let provenance = evidence_entries
        .iter()
        .map(|entry| entry.key.clone())
        .collect::<Vec<_>>();
    let evidence = evidence_entries
        .iter()
        .map(|entry| Evidence {
            source: entry.key.clone(),
            quote: entry.content.clone(),
            span_start: None,
            span_end: None,
        })
        .collect::<Vec<_>>();
    let grounded = !evidence.is_empty() && !provenance.is_empty();
    GroundedResponse {
        answer: answer.to_string(),
        confidence: if grounded { 0.75 } else { 0.2 },
        provenance,
        evidence,
        repro_steps: vec![
            format!(
                "Inspect runtime traces under {}",
                workspace_dir.join("state").display()
            ),
            "Review this artifact for the exact request and response pair".to_string(),
        ],
        grounded,
        red_badge: !grounded,
    }
}

fn build_turn(
    index: usize,
    agent: &str,
    content: &str,
    workspace_dir: &Path,
    evidence_entries: &[MemoryEntry],
) -> TurnRecord {
    TurnRecord {
        index,
        timestamp: now_iso(),
        agent: agent.to_string(),
        content: content.to_string(),
        metadata: TurnMetadata {
            verified_count: 0,
            unverified_count: 0,
            citation_rate: 0.0,
        },
        grounded_response: build_grounded_response(content, workspace_dir, evidence_entries),
    }
}

pub fn write_single_message_artifact(
    workspace_dir: &Path,
    session_id: Option<&str>,
    topic: &str,
    model: &str,
    user_message: &str,
    response: &str,
    status: &str,
) -> Result<PathBuf> {
    write_single_message_artifact_with_memory(
        workspace_dir,
        session_id,
        topic,
        model,
        user_message,
        response,
        status,
        &[],
    )
}

pub fn write_single_message_artifact_with_memory(
    workspace_dir: &Path,
    session_id: Option<&str>,
    topic: &str,
    model: &str,
    user_message: &str,
    response: &str,
    status: &str,
    evidence_entries: &[MemoryEntry],
) -> Result<PathBuf> {
    let session_id = session_id
        .map(str::to_string)
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| Uuid::new_v4().to_string());
    let dir = artifact_dir(workspace_dir);
    fs::create_dir_all(&dir)?;

    let artifact = SessionArtifact {
        schema_version: SCHEMA_VERSION.to_string(),
        session_id: session_id.clone(),
        status: status.to_string(),
        topic: topic.to_string(),
        model: model.to_string(),
        recursive_depth: 0,
        started_at: now_iso(),
        completed_at: now_iso(),
        library_path: workspace_dir.display().to_string(),
        log_path: workspace_dir
            .join("state")
            .join("runtime-trace.jsonl")
            .display()
            .to_string(),
        loaded_papers_count: 0,
        loaded_papers: Vec::new(),
        metrics: serde_json::json!({}),
        summary: response.to_string(),
        turns: vec![
            build_turn(1, "USER", user_message, workspace_dir, &[]),
            build_turn(2, "R.A.I.N.", response, workspace_dir, evidence_entries),
        ],
    };

    let safe_session_id = session_id.replace(['/', '\\', ':', '*', '?', '"', '<', '>', '|'], "_");
    let path = dir.join(format!("session_{safe_session_id}.json"));
    fs::write(&path, serde_json::to_vec_pretty(&artifact)?)?;
    Ok(path)
}
