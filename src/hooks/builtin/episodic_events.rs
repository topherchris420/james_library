use crate::autonomy::episodic::{EPISODIC_SCHEMA_VERSION, EpisodicEventV2, EventOutcome};
use crate::hooks::traits::HookHandler;
use crate::tools::traits::ToolResult;
use async_trait::async_trait;
use std::path::PathBuf;
use std::time::Duration;

/// Built-in hook that appends one `EpisodicEventV2` JSONL line per tool call
/// to `episodic_memory/episodic_events.jsonl` in the workspace. The Python
/// `episodic_memory_ingestor.py` tails this stream and segments it into
/// episodes.
///
/// Privacy contract: tool arguments and outputs are **not** recorded — both
/// can carry sensitive payloads and the stream is plaintext. Only the tool
/// name, outcome, and duration are written.
pub struct EpisodicEventsHook {
    workspace_dir: PathBuf,
    agent_name: String,
}

impl EpisodicEventsHook {
    pub fn new(workspace_dir: PathBuf) -> Self {
        Self {
            workspace_dir,
            agent_name: "R.A.I.N.Agent".to_string(),
        }
    }
}

#[async_trait]
impl HookHandler for EpisodicEventsHook {
    fn name(&self) -> &str {
        "episodic-events"
    }

    fn priority(&self) -> i32 {
        -40
    }

    async fn on_after_tool_call(&self, tool: &str, result: &ToolResult, duration: Duration) {
        let outcome = if result.success {
            EventOutcome::Success
        } else {
            EventOutcome::Failure
        };
        let outcome_word = if result.success { "success" } else { "failure" };
        #[allow(clippy::cast_possible_truncation)]
        let duration_ms = duration.as_millis() as u64;

        let event = EpisodicEventV2 {
            timestamp: chrono::Utc::now().to_rfc3339(),
            agent_name: self.agent_name.clone(),
            tool: tool.to_string(),
            args: serde_json::Value::Object(serde_json::Map::new()),
            sentence: format!(
                "{} ran tool '{tool}' ({outcome_word}, {duration_ms} ms)",
                self.agent_name
            ),
            duration_ms,
            schema_version: Some(EPISODIC_SCHEMA_VERSION),
            episode_id: None,
            session_id: None,
            channel: None,
            state: None,
            outcome: Some(outcome),
        };

        if let Err(e) = crate::autonomy::episodic::append_event(&self.workspace_dir, &event).await {
            tracing::warn!("episodic-events hook: failed to append event: {e}");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::autonomy::episodic::episodic_events_path;

    #[tokio::test]
    async fn writes_v2_event_per_tool_call_without_payloads() {
        let dir = tempfile::tempdir().unwrap();
        let hook = EpisodicEventsHook::new(dir.path().to_path_buf());

        let result = ToolResult {
            success: true,
            output: "sensitive file contents".into(),
            error: None,
        };
        hook.on_after_tool_call("file_read", &result, Duration::from_millis(12))
            .await;

        let failed = ToolResult {
            success: false,
            output: String::new(),
            error: Some("token=do-not-log".into()),
        };
        hook.on_after_tool_call("shell", &failed, Duration::from_millis(40))
            .await;

        let content = tokio::fs::read_to_string(episodic_events_path(dir.path()))
            .await
            .unwrap();
        let events: Vec<EpisodicEventV2> = content
            .lines()
            .map(|l| EpisodicEventV2::from_jsonl(l).unwrap())
            .collect();

        assert_eq!(events.len(), 2);
        assert_eq!(events[0].tool, "file_read");
        assert_eq!(events[0].outcome, Some(EventOutcome::Success));
        assert_eq!(events[1].outcome, Some(EventOutcome::Failure));
        // Privacy: neither tool output nor error text reaches the stream.
        assert!(!content.contains("sensitive file contents"));
        assert!(!content.contains("do-not-log"));
        // Identity-safe actor label only.
        assert!(content.contains("R.A.I.N.Agent"));
    }
}
