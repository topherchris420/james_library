use async_trait::async_trait;
use serde::Serialize;
use serde_json::Value;
use std::path::PathBuf;
use std::time::Duration;
use tokio::sync::mpsc;

use crate::hooks::traits::HookHandler;
use crate::tools::traits::ToolResult;

/// A single episodic memory event emitted after a successful tool call.
#[derive(Debug, Serialize)]
struct EpisodicEvent {
    timestamp: String,
    agent_name: String,
    tool: String,
    args: Value,
    sentence: String,
    duration_ms: u64,
}

/// Translates a structured tool call into a past-tense natural language sentence.
fn translate_tool_call(agent: &str, tool: &str, args: &Value) -> String {
    match tool {
        "arxiv_search" => {
            let query = args
                .get("query")
                .and_then(|v| v.as_str())
                .unwrap_or("unknown topic");
            format!("Agent {agent} searched arXiv for '{query}'.")
        }
        "file_read" => {
            let path = args
                .get("path")
                .and_then(|v| v.as_str())
                .unwrap_or("unknown file");
            let label = std::path::Path::new(path)
                .file_stem()
                .and_then(|s| s.to_str())
                .unwrap_or(path);
            format!("Agent {agent} read the file '{label}'.")
        }
        "file_write" => {
            let path = args
                .get("path")
                .and_then(|v| v.as_str())
                .unwrap_or("unknown file");
            let label = std::path::Path::new(path)
                .file_stem()
                .and_then(|s| s.to_str())
                .unwrap_or(path);
            format!("Agent {agent} wrote to the file '{label}'.")
        }
        "file_edit" => {
            let path = args
                .get("path")
                .and_then(|v| v.as_str())
                .unwrap_or("unknown file");
            let label = std::path::Path::new(path)
                .file_stem()
                .and_then(|s| s.to_str())
                .unwrap_or(path);
            format!("Agent {agent} edited the file '{label}'.")
        }
        "content_search" => {
            let pattern = args
                .get("pattern")
                .and_then(|v| v.as_str())
                .unwrap_or("unknown pattern");
            format!("Agent {agent} searched content for pattern '{pattern}'.")
        }
        "web_search_tool" => {
            let query = args
                .get("query")
                .and_then(|v| v.as_str())
                .unwrap_or("unknown query");
            format!("Agent {agent} searched the web for '{query}'.")
        }
        "shell" => {
            let cmd = args
                .get("command")
                .and_then(|v| v.as_str())
                .unwrap_or("unknown command");
            let short = if cmd.chars().count() > 60 { cmd.chars().take(60).collect::<String>() } else { cmd.to_string() };
            format!("Agent {agent} executed shell command '{short}'.")
        }
        "memory_store" => {
            let key = args
                .get("key")
                .and_then(|v| v.as_str())
                .unwrap_or("unknown key");
            format!("Agent {agent} stored a memory with key '{key}'.")
        }
        "memory_recall" => {
            let query = args
                .get("query")
                .and_then(|v| v.as_str())
                .unwrap_or("unknown query");
            format!("Agent {agent} recalled memories matching '{query}'.")
        }
        "glob_search" => {
            let pattern = args
                .get("pattern")
                .and_then(|v| v.as_str())
                .unwrap_or("unknown pattern");
            format!("Agent {agent} searched for files matching '{pattern}'.")
        }
        "git_operations" => {
            let action = args
                .get("action")
                .and_then(|v| v.as_str())
                .unwrap_or("unknown action");
            format!("Agent {agent} performed git '{action}'.")
        }
        "web_fetch" => {
            let url = args
                .get("url")
                .and_then(|v| v.as_str())
                .unwrap_or("unknown URL");
            format!("Agent {agent} fetched content from '{url}'.")
        }
        "pdf_read" => {
            let path = args
                .get("path")
                .and_then(|v| v.as_str())
                .unwrap_or("unknown file");
            let label = std::path::Path::new(path)
                .file_stem()
                .and_then(|s| s.to_str())
                .unwrap_or(path);
            format!("Agent {agent} read PDF '{label}'.")
        }
        _ => {
            let args_str = serde_json::to_string(args).unwrap_or_default();
            let short_args = if args_str.chars().count() > 120 {
                format!("{}...", args_str.chars().take(120).collect::<String>())
            } else {
                args_str
            };
            format!("Agent {agent} executed the {tool} tool with arguments: {short_args}.")
        }
    }
}

/// Hook that intercepts successful tool calls, translates them into natural
/// language episodic sentences, and writes them as JSONL to a file for the
/// Python graph bridge to consume asynchronously.
///
/// Communication with the Python layer uses a JSONL file at
/// `<output_dir>/episodic_events.jsonl`. The hook writes one JSON object per
/// line. The Python `EpisodicMemoryIngestor` tails this file for ingestion.
pub struct EpisodicMemoryHook {
    agent_name: String,
    tx: mpsc::UnboundedSender<EpisodicEvent>,
}

impl EpisodicMemoryHook {
    /// Create a new episodic memory hook.
    ///
    /// `agent_name`: label for the agent (e.g. "James", "Luca").
    /// `output_dir`: directory where `episodic_events.jsonl` is written.
    ///
    /// Spawns a background tokio task that drains events and appends to the
    /// JSONL file, so the hook itself never blocks.
    pub fn new(agent_name: impl Into<String>, output_dir: impl Into<PathBuf>) -> Self {
        let agent_name = agent_name.into();
        let output_dir = output_dir.into();
        let (tx, rx) = mpsc::unbounded_channel();

        tokio::spawn(Self::writer_task(output_dir, rx));

        Self { agent_name, tx }
    }

    /// Background writer: receives events and appends JSONL lines.
    async fn writer_task(output_dir: PathBuf, mut rx: mpsc::UnboundedReceiver<EpisodicEvent>) {
        use tokio::fs::{create_dir_all, OpenOptions};
        use tokio::io::AsyncWriteExt;

        if let Err(e) = create_dir_all(&output_dir).await {
            tracing::error!(dir = %output_dir.display(), "Failed to create episodic memory dir: {e}");
            return;
        }

        let path = output_dir.join("episodic_events.jsonl");

        while let Some(event) = rx.recv().await {
            let line = match serde_json::to_string(&event) {
                Ok(json) => format!("{json}\n"),
                Err(e) => {
                    tracing::warn!("Failed to serialize episodic event: {e}");
                    continue;
                }
            };

            match OpenOptions::new()
                .create(true)
                .append(true)
                .open(&path)
                .await
            {
                Ok(mut f) => {
                    if let Err(e) = f.write_all(line.as_bytes()).await {
                        tracing::warn!(path = %path.display(), "Failed to write episodic event: {e}");
                    }
                }
                Err(e) => {
                    tracing::warn!(path = %path.display(), "Failed to open episodic events file: {e}");
                }
            }
        }
    }
}

#[async_trait]
impl HookHandler for EpisodicMemoryHook {
    fn name(&self) -> &str {
        "episodic-memory"
    }

    fn priority(&self) -> i32 {
        // Run after command-logger (-50), low priority fire-and-forget.
        -100
    }

    async fn on_after_tool_call(
        &self,
        tool: &str,
        args: &Value,
        result: &ToolResult,
        duration: Duration,
    ) {
        // Only record successful tool calls as episodic memory.
        if !result.success {
            return;
        }

        let sentence = translate_tool_call(&self.agent_name, tool, args);

        let event = EpisodicEvent {
            timestamp: chrono::Utc::now().to_rfc3339(),
            agent_name: self.agent_name.clone(),
            tool: tool.to_string(),
            args: args.clone(),
            sentence,
            duration_ms: u64::try_from(duration.as_millis()).unwrap_or(u64::MAX),
        };

        // Non-blocking send; if the writer task is gone, just drop silently.
        let _ = self.tx.send(event);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn translate_arxiv_search() {
        let args = serde_json::json!({"query": "cymatics"});
        let sentence = translate_tool_call("James", "arxiv_search", &args);
        assert_eq!(sentence, "Agent James searched arXiv for 'cymatics'.");
    }

    #[test]
    fn translate_file_read() {
        let args = serde_json::json!({"path": "papers/Dynamic Resonance Rooting.md"});
        let sentence = translate_tool_call("Luca", "file_read", &args);
        assert_eq!(
            sentence,
            "Agent Luca read the file 'Dynamic Resonance Rooting'."
        );
    }

    #[test]
    fn translate_file_write() {
        let args = serde_json::json!({"path": "/tmp/output.txt"});
        let sentence = translate_tool_call("James", "file_write", &args);
        assert_eq!(sentence, "Agent James wrote to the file 'output'.");
    }

    #[test]
    fn translate_content_search() {
        let args = serde_json::json!({"pattern": "resonance"});
        let sentence = translate_tool_call("Elena", "content_search", &args);
        assert_eq!(
            sentence,
            "Agent Elena searched content for pattern 'resonance'."
        );
    }

    #[test]
    fn translate_web_search() {
        let args = serde_json::json!({"query": "quantum coherence"});
        let sentence = translate_tool_call("Alex", "web_search_tool", &args);
        assert_eq!(
            sentence,
            "Agent Alex searched the web for 'quantum coherence'."
        );
    }

    #[test]
    fn translate_unknown_tool_fallback() {
        let args = serde_json::json!({"foo": "bar"});
        let sentence = translate_tool_call("James", "custom_tool", &args);
        assert!(sentence.starts_with("Agent James executed the custom_tool tool"));
        assert!(sentence.contains("foo"));
    }

    #[test]
    fn translate_shell() {
        let args = serde_json::json!({"command": "ls -la"});
        let sentence = translate_tool_call("James", "shell", &args);
        assert_eq!(sentence, "Agent James executed shell command 'ls -la'.");
    }

    #[test]
    fn translate_memory_store() {
        let args = serde_json::json!({"key": "cymatics_findings"});
        let sentence = translate_tool_call("James", "memory_store", &args);
        assert_eq!(
            sentence,
            "Agent James stored a memory with key 'cymatics_findings'."
        );
    }

    #[test]
    fn translate_memory_recall() {
        let args = serde_json::json!({"query": "resonance patterns"});
        let sentence = translate_tool_call("James", "memory_recall", &args);
        assert_eq!(
            sentence,
            "Agent James recalled memories matching 'resonance patterns'."
        );
    }

    #[test]
    fn translate_pdf_read() {
        let args = serde_json::json!({"path": "papers/quantum.pdf"});
        let sentence = translate_tool_call("Luca", "pdf_read", &args);
        assert_eq!(sentence, "Agent Luca read PDF 'quantum'.");
    }

    #[tokio::test]
    async fn hook_only_records_successful_calls() {
        let dir = tempfile::tempdir().unwrap();
        let hook = EpisodicMemoryHook::new("TestAgent", dir.path().to_path_buf());

        // Failed call — should not be recorded
        let fail_result = ToolResult {
            success: false,
            output: "error".into(),
            error: Some("boom".into()),
        };
        hook.on_after_tool_call(
            "shell",
            &serde_json::json!({"command": "bad"}),
            &fail_result,
            Duration::from_millis(10),
        )
        .await;

        // Successful call — should be recorded
        let ok_result = ToolResult {
            success: true,
            output: "ok".into(),
            error: None,
        };
        hook.on_after_tool_call(
            "arxiv_search",
            &serde_json::json!({"query": "cymatics"}),
            &ok_result,
            Duration::from_millis(200),
        )
        .await;

        // Give the writer task time to flush
        tokio::time::sleep(Duration::from_millis(100)).await;

        let content = tokio::fs::read_to_string(dir.path().join("episodic_events.jsonl"))
            .await
            .unwrap();
        let lines: Vec<&str> = content.trim().lines().collect();
        assert_eq!(lines.len(), 1);
        assert!(lines[0].contains("cymatics"));
        assert!(lines[0].contains("Agent TestAgent searched arXiv"));
    }
}
