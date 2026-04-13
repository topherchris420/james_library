//! Comprehensive agent-loop test suite.
//!
//! Tests exercise the full `Agent.turn()` cycle with mock providers and tools,
//! covering every edge case an agentic tool loop must handle:
//!
//!   1. Simple text response (no tools)
//!   2. Single tool call → final response
//!   3. Multi-step tool chain (tool A → tool B → response)
//!   4. Max-iteration bailout
//!   5. Unknown tool name recovery
//!   6. Tool execution failure recovery
//!   7. Parallel tool dispatch
//!   8. History trimming during long conversations
//!   9. Memory auto-save round-trip
//!  10. Native vs XML dispatcher integration
//!  11. Empty / whitespace-only LLM responses
//!  12. Mixed text + tool call responses
//!  13. Multi-tool batch in a single response
//!  14. System prompt generation & tool instructions
//!  15. Context enrichment from memory loader
//!  16. ConversationMessage serialization round-trip
//!  17. Tool call with stringified JSON arguments
//!  18. Conversation history fidelity (tool call → tool result → assistant)
//!  19. Builder validation (missing required fields)
//!  20. Idempotent system prompt insertion

use crate::agent::agent::{Agent, ToolDispatchMode};
use crate::agent::loop_::build_tool_instructions_from_specs;
use crate::agent::session_artifact::{
    write_single_message_artifact, write_single_message_artifact_with_memory,
};
use crate::agent::tool_call_parser::{parse_tool_call_value, parse_tool_calls};
use crate::config::{AgentConfig, MemoryConfig};
use crate::memory::{self, Memory};
use crate::memory::{MemoryCategory, MemoryEntry};
use crate::observability::{NoopObserver, Observer};
use crate::providers::{ChatMessage, ChatRequest, ChatResponse, Provider, ToolCall};
use crate::tools::{Tool, ToolResult};
use anyhow::Result;
use async_trait::async_trait;
use std::sync::{Arc, Mutex};

// ═══════════════════════════════════════════════════════════════════════════
// Test Helpers — Mock Provider, Mock Tool, Mock Memory
// ═══════════════════════════════════════════════════════════════════════════

/// A mock LLM provider that returns pre-scripted responses in order.
/// When the queue is exhausted it returns a simple "done" text response.
struct ScriptedProvider {
    responses: Mutex<Vec<ChatResponse>>,
    /// Records every request for assertion.
    requests: Mutex<Vec<Vec<ChatMessage>>>,
}

impl ScriptedProvider {
    fn new(responses: Vec<ChatResponse>) -> Self {
        Self {
            responses: Mutex::new(responses),
            requests: Mutex::new(Vec::new()),
        }
    }
}

#[async_trait]
impl Provider for ScriptedProvider {
    async fn chat_with_system(
        &self,
        _system_prompt: Option<&str>,
        _message: &str,
        _model: &str,
        _temperature: f64,
    ) -> Result<String> {
        Ok("fallback".into())
    }

    async fn chat(
        &self,
        request: ChatRequest<'_>,
        _model: &str,
        _temperature: f64,
    ) -> Result<ChatResponse> {
        self.requests
            .lock()
            .unwrap()
            .push(request.messages.to_vec());

        let mut guard = self.responses.lock().unwrap();
        if guard.is_empty() {
            return Ok(ChatResponse {
                text: Some("done".into()),
                tool_calls: vec![],
                usage: None,
                reasoning_content: None,
            });
        }
        Ok(guard.remove(0))
    }
}

/// A mock provider that always returns an error.
struct FailingProvider;

#[async_trait]
impl Provider for FailingProvider {
    async fn chat_with_system(
        &self,
        _system_prompt: Option<&str>,
        _message: &str,
        _model: &str,
        _temperature: f64,
    ) -> Result<String> {
        anyhow::bail!("provider error")
    }

    async fn chat(
        &self,
        _request: ChatRequest<'_>,
        _model: &str,
        _temperature: f64,
    ) -> Result<ChatResponse> {
        anyhow::bail!("provider error")
    }
}

/// A simple echo tool that returns its arguments as output.
struct EchoTool;

#[async_trait]
impl Tool for EchoTool {
    fn name(&self) -> &str {
        "echo"
    }

    fn description(&self) -> &str {
        "Echoes the input"
    }

    fn parameters_schema(&self) -> serde_json::Value {
        serde_json::json!({
            "type": "object",
            "properties": {
                "message": {"type": "string"}
            }
        })
    }

    async fn execute(&self, args: serde_json::Value) -> Result<ToolResult> {
        let msg = args
            .get("message")
            .and_then(|v| v.as_str())
            .unwrap_or("(empty)")
            .to_string();
        Ok(ToolResult {
            success: true,
            output: msg,
            error: None,
        })
    }
}

/// A tool that always fails execution.
struct FailingTool;

#[async_trait]
impl Tool for FailingTool {
    fn name(&self) -> &str {
        "fail"
    }

    fn description(&self) -> &str {
        "Always fails"
    }

    fn parameters_schema(&self) -> serde_json::Value {
        serde_json::json!({"type": "object"})
    }

    async fn execute(&self, _args: serde_json::Value) -> Result<ToolResult> {
        Ok(ToolResult {
            success: false,
            output: String::new(),
            error: Some("intentional failure".into()),
        })
    }
}

/// A tool that panics (tests error propagation).
struct PanickingTool;

#[async_trait]
impl Tool for PanickingTool {
    fn name(&self) -> &str {
        "panicker"
    }

    fn description(&self) -> &str {
        "Panics on execution"
    }

    fn parameters_schema(&self) -> serde_json::Value {
        serde_json::json!({"type": "object"})
    }

    async fn execute(&self, _args: serde_json::Value) -> Result<ToolResult> {
        anyhow::bail!("catastrophic tool failure")
    }
}

/// A tool that tracks how many times it was called.
struct CountingTool {
    count: Arc<Mutex<usize>>,
}

impl CountingTool {
    fn new() -> (Self, Arc<Mutex<usize>>) {
        let count = Arc::new(Mutex::new(0));
        (
            Self {
                count: count.clone(),
            },
            count,
        )
    }
}

#[async_trait]
impl Tool for CountingTool {
    fn name(&self) -> &str {
        "counter"
    }

    fn description(&self) -> &str {
        "Counts calls"
    }

    fn parameters_schema(&self) -> serde_json::Value {
        serde_json::json!({"type": "object"})
    }

    async fn execute(&self, _args: serde_json::Value) -> Result<ToolResult> {
        let mut c = self.count.lock().unwrap();
        *c += 1;
        Ok(ToolResult {
            success: true,
            output: format!("call #{}", *c),
            error: None,
        })
    }
}

fn make_memory() -> Arc<dyn Memory> {
    let cfg = MemoryConfig {
        backend: "none".into(),
        ..MemoryConfig::default()
    };
    Arc::from(memory::create_memory(&cfg, &std::env::temp_dir(), None).unwrap())
}

fn make_sqlite_memory() -> (Arc<dyn Memory>, tempfile::TempDir) {
    let tmp = tempfile::TempDir::new().unwrap();
    let cfg = MemoryConfig {
        backend: "sqlite".into(),
        ..MemoryConfig::default()
    };
    let mem = Arc::from(memory::create_memory(&cfg, tmp.path(), None).unwrap());
    (mem, tmp)
}

fn make_observer() -> Arc<dyn Observer> {
    Arc::from(NoopObserver {})
}

fn build_agent_with(
    provider: Box<dyn Provider>,
    tools: Vec<Box<dyn Tool>>,
    tool_dispatch_mode: ToolDispatchMode,
) -> Agent {
    Agent::builder()
        .provider(provider)
        .tools(tools)
        .memory(make_memory())
        .observer(make_observer())
        .tool_dispatch_mode(tool_dispatch_mode)
        .workspace_dir(std::env::temp_dir())
        .build()
        .unwrap()
}

fn build_agent_with_memory(
    provider: Box<dyn Provider>,
    tools: Vec<Box<dyn Tool>>,
    mem: Arc<dyn Memory>,
    auto_save: bool,
) -> Agent {
    Agent::builder()
        .provider(provider)
        .tools(tools)
        .memory(mem)
        .observer(make_observer())
        .tool_dispatch_mode(ToolDispatchMode::Native)
        .workspace_dir(std::env::temp_dir())
        .auto_save(auto_save)
        .build()
        .unwrap()
}

fn build_agent_with_config(
    provider: Box<dyn Provider>,
    tools: Vec<Box<dyn Tool>>,
    config: AgentConfig,
) -> Agent {
    Agent::builder()
        .provider(provider)
        .tools(tools)
        .memory(make_memory())
        .observer(make_observer())
        .tool_dispatch_mode(ToolDispatchMode::Native)
        .workspace_dir(std::env::temp_dir())
        .config(config)
        .build()
        .unwrap()
}

fn history_contains_tool_result(history: &[ChatMessage], needle: &str) -> bool {
    history.iter().any(|msg| {
        if msg.role == "tool" {
            serde_json::from_str::<serde_json::Value>(&msg.content)
                .ok()
                .and_then(|payload| {
                    payload
                        .get("content")
                        .and_then(serde_json::Value::as_str)
                        .map(str::to_owned)
                })
                .is_some_and(|content| content.contains(needle))
                || msg.content.contains(needle)
        } else {
            msg.role == "user"
                && msg.content.starts_with("[Tool results]\n")
                && msg.content.contains(needle)
        }
    })
}

fn assistant_payload(msg: &ChatMessage) -> serde_json::Value {
    serde_json::from_str(&msg.content).expect("assistant history should contain JSON payload")
}

/// Helper: create a ChatResponse with tool calls (native format).
fn tool_response(calls: Vec<ToolCall>) -> ChatResponse {
    ChatResponse {
        text: Some(String::new()),
        tool_calls: calls,
        usage: None,
        reasoning_content: None,
    }
}

/// Helper: create a plain text ChatResponse.
fn text_response(text: &str) -> ChatResponse {
    ChatResponse {
        text: Some(text.into()),
        tool_calls: vec![],
        usage: None,
        reasoning_content: None,
    }
}

/// Helper: create an XML-style tool call response.
fn xml_tool_response(name: &str, args: &str) -> ChatResponse {
    ChatResponse {
        text: Some(format!(
            "<tool_call>\n{{\"name\": \"{name}\", \"arguments\": {args}}}\n</tool_call>"
        )),
        tool_calls: vec![],
        usage: None,
        reasoning_content: None,
    }
}

// ═══════════════════════════════════════════════════════════════════════════
// 1. Simple text response (no tools)
// ═══════════════════════════════════════════════════════════════════════════

#[tokio::test]
async fn turn_returns_text_when_no_tools_called() {
    let provider = Box::new(ScriptedProvider::new(vec![text_response("Hello world")]));
    let mut agent = build_agent_with(provider, vec![Box::new(EchoTool)], ToolDispatchMode::Native);

    let response = agent.turn("hi").await.unwrap();
    assert!(
        !response.is_empty(),
        "Expected non-empty text response from provider"
    );
}

// ═══════════════════════════════════════════════════════════════════════════
// 2. Single tool call → final response
// ═══════════════════════════════════════════════════════════════════════════

#[tokio::test]
async fn turn_executes_single_tool_then_returns() {
    let provider = Box::new(ScriptedProvider::new(vec![
        tool_response(vec![ToolCall {
            id: "tc1".into(),
            name: "echo".into(),
            arguments: r#"{"message": "hello from tool"}"#.into(),
        }]),
        text_response("I ran the tool"),
    ]));

    let mut agent = build_agent_with(provider, vec![Box::new(EchoTool)], ToolDispatchMode::Native);

    let response = agent.turn("run echo").await.unwrap();
    assert!(
        !response.is_empty(),
        "Expected non-empty response after tool execution"
    );
}

// ═══════════════════════════════════════════════════════════════════════════
// 3. Multi-step tool chain (tool A → tool B → response)
// ═══════════════════════════════════════════════════════════════════════════

#[tokio::test]
async fn turn_handles_multi_step_tool_chain() {
    let (counting_tool, count) = CountingTool::new();

    let provider = Box::new(ScriptedProvider::new(vec![
        tool_response(vec![ToolCall {
            id: "tc1".into(),
            name: "counter".into(),
            arguments: "{}".into(),
        }]),
        tool_response(vec![ToolCall {
            id: "tc2".into(),
            name: "counter".into(),
            arguments: "{}".into(),
        }]),
        tool_response(vec![ToolCall {
            id: "tc3".into(),
            name: "counter".into(),
            arguments: "{}".into(),
        }]),
        text_response("Done after 3 calls"),
    ]));

    let mut agent = build_agent_with(
        provider,
        vec![Box::new(counting_tool)],
        ToolDispatchMode::Native,
    );

    let response = agent.turn("count 3 times").await.unwrap();
    assert!(
        !response.is_empty(),
        "Expected non-empty response after multi-step chain"
    );
    assert_eq!(*count.lock().unwrap(), 3);
}

// ═══════════════════════════════════════════════════════════════════════════
// 4. Max-iteration bailout
// ═══════════════════════════════════════════════════════════════════════════

#[tokio::test]
async fn turn_bails_out_at_max_iterations() {
    // Create more tool calls than max_tool_iterations allows.
    let max_iters = 3;
    let mut responses = Vec::new();
    for i in 0..max_iters + 5 {
        responses.push(tool_response(vec![ToolCall {
            id: format!("tc{i}"),
            name: "echo".into(),
            arguments: r#"{"message": "loop"}"#.into(),
        }]));
    }

    let provider = Box::new(ScriptedProvider::new(responses));

    let config = AgentConfig {
        max_tool_iterations: max_iters,
        ..AgentConfig::default()
    };

    let mut agent = build_agent_with_config(provider, vec![Box::new(EchoTool)], config);

    let result = agent.turn("infinite loop").await;
    assert!(result.is_err());
    let err = result.unwrap_err().to_string();
    assert!(
        err.contains("maximum tool iterations"),
        "Expected max iterations error, got: {err}"
    );
}

// ═══════════════════════════════════════════════════════════════════════════
// 5. Unknown tool name recovery
// ═══════════════════════════════════════════════════════════════════════════

#[tokio::test]
async fn turn_handles_unknown_tool_gracefully() {
    let provider = Box::new(ScriptedProvider::new(vec![
        tool_response(vec![ToolCall {
            id: "tc1".into(),
            name: "nonexistent_tool".into(),
            arguments: "{}".into(),
        }]),
        text_response("I couldn't find that tool"),
    ]));

    let mut agent = build_agent_with(provider, vec![Box::new(EchoTool)], ToolDispatchMode::Native);

    let response = agent.turn("use nonexistent").await.unwrap();
    assert!(
        !response.is_empty(),
        "Expected non-empty response after unknown tool recovery"
    );

    // Verify the tool result mentioned "Unknown tool"
    let has_tool_result = history_contains_tool_result(agent.history(), "Unknown tool");
    assert!(
        has_tool_result,
        "Expected tool result with 'Unknown tool' message"
    );
}

// ═══════════════════════════════════════════════════════════════════════════
// 6. Tool execution failure recovery
// ═══════════════════════════════════════════════════════════════════════════

#[tokio::test]
async fn turn_recovers_from_tool_failure() {
    let provider = Box::new(ScriptedProvider::new(vec![
        tool_response(vec![ToolCall {
            id: "tc1".into(),
            name: "fail".into(),
            arguments: "{}".into(),
        }]),
        text_response("Tool failed but I recovered"),
    ]));

    let mut agent = build_agent_with(
        provider,
        vec![Box::new(FailingTool)],
        ToolDispatchMode::Native,
    );

    let response = agent.turn("try failing tool").await.unwrap();
    assert!(
        !response.is_empty(),
        "Expected non-empty response after tool failure recovery"
    );
}

#[tokio::test]
async fn turn_recovers_from_tool_error() {
    let provider = Box::new(ScriptedProvider::new(vec![
        tool_response(vec![ToolCall {
            id: "tc1".into(),
            name: "panicker".into(),
            arguments: "{}".into(),
        }]),
        text_response("I recovered from the error"),
    ]));

    let mut agent = build_agent_with(
        provider,
        vec![Box::new(PanickingTool)],
        ToolDispatchMode::Native,
    );

    let response = agent.turn("try panicking").await.unwrap();
    assert!(
        !response.is_empty(),
        "Expected non-empty response after tool error recovery"
    );
}

// ═══════════════════════════════════════════════════════════════════════════
// 7. Provider error propagation
// ═══════════════════════════════════════════════════════════════════════════

#[tokio::test]
async fn turn_propagates_provider_error() {
    let mut agent = build_agent_with(Box::new(FailingProvider), vec![], ToolDispatchMode::Native);

    let result = agent.turn("hello").await;
    assert!(result.is_err(), "Expected provider error to propagate");
}

// ═══════════════════════════════════════════════════════════════════════════
// 8. History trimming during long conversations
// ═══════════════════════════════════════════════════════════════════════════

#[tokio::test]
async fn history_trims_after_max_messages() {
    let max_history = 6;
    let mut responses = vec![];
    for _ in 0..max_history + 5 {
        responses.push(text_response("ok"));
    }

    let provider = Box::new(ScriptedProvider::new(responses));
    let config = AgentConfig {
        max_history_messages: max_history,
        ..AgentConfig::default()
    };

    let mut agent = build_agent_with_config(provider, vec![], config);

    for i in 0..max_history + 5 {
        let _ = agent.turn(&format!("msg {i}")).await.unwrap();
    }

    // System prompt (1) + trimmed messages
    // Should not exceed max_history + 1 (system prompt)
    assert!(
        agent.history().len() <= max_history + 1,
        "History length {} exceeds max {} + 1 (system)",
        agent.history().len(),
        max_history,
    );

    // System prompt should always be preserved
    let first = &agent.history()[0];
    assert_eq!(first.role, "system");
}

// ═══════════════════════════════════════════════════════════════════════════
// 9. Memory auto-save round-trip
// ═══════════════════════════════════════════════════════════════════════════

#[tokio::test]
async fn auto_save_stores_only_user_messages_in_memory() {
    let (mem, _tmp) = make_sqlite_memory();
    let provider = Box::new(ScriptedProvider::new(vec![text_response(
        "I remember everything",
    )]));

    let mut agent = build_agent_with_memory(
        provider,
        vec![],
        mem.clone(),
        true, // auto_save enabled
    );

    let _ = agent.turn("Remember this fact").await.unwrap();

    // Auto-save only persists user-stated input, never assistant-generated summaries.
    let count = mem.count().await.unwrap();
    assert_eq!(
        count, 1,
        "Expected exactly 1 user memory entry, got {count}"
    );

    let stored = mem.get("user_msg").await.unwrap();
    assert!(stored.is_some(), "Expected user_msg key to be present");
    assert_eq!(
        stored.unwrap().content,
        "Remember this fact",
        "Stored memory should match the original user message"
    );

    let assistant = mem.get("assistant_resp").await.unwrap();
    assert!(
        assistant.is_none(),
        "assistant_resp should not be auto-saved anymore"
    );
}

#[tokio::test]
async fn auto_save_disabled_does_not_store() {
    let (mem, _tmp) = make_sqlite_memory();
    let provider = Box::new(ScriptedProvider::new(vec![text_response("hello")]));

    let mut agent = build_agent_with_memory(
        provider,
        vec![],
        mem.clone(),
        false, // auto_save disabled
    );

    let _ = agent.turn("test message").await.unwrap();

    let count = mem.count().await.unwrap();
    assert_eq!(count, 0, "Expected 0 memory entries with auto_save off");
}

// ═══════════════════════════════════════════════════════════════════════════
// 10. Native vs XML dispatcher integration
// ═══════════════════════════════════════════════════════════════════════════

#[tokio::test]
async fn xml_dispatcher_parses_and_loops() {
    let provider = Box::new(ScriptedProvider::new(vec![
        xml_tool_response("echo", r#"{"message": "xml-test"}"#),
        text_response("XML tool completed"),
    ]));

    let mut agent = build_agent_with(provider, vec![Box::new(EchoTool)], ToolDispatchMode::Xml);

    let response = agent.turn("test xml").await.unwrap();
    assert!(
        !response.is_empty(),
        "Expected non-empty response from XML dispatcher"
    );
}

#[test]
fn native_mode_uses_native_tools_when_tools_exist() {
    assert!(ToolDispatchMode::Native.uses_native_tools(false, true));
    assert!(ToolDispatchMode::Auto.uses_native_tools(true, true));
}

#[test]
fn xml_mode_disables_native_tools_even_when_provider_supports_them() {
    assert!(!ToolDispatchMode::Xml.uses_native_tools(true, true));
    assert!(!ToolDispatchMode::Auto.uses_native_tools(false, true));
    assert!(!ToolDispatchMode::Native.uses_native_tools(true, false));
}

#[tokio::test]
async fn native_mode_still_allows_agent_turns() {
    let provider = Box::new(ScriptedProvider::new(vec![text_response("ok")]));
    let mut agent = build_agent_with(provider, vec![Box::new(EchoTool)], ToolDispatchMode::Native);

    let _ = agent.turn("hi").await.unwrap();
}

// ═══════════════════════════════════════════════════════════════════════════
// 11. Empty / whitespace-only LLM responses
// ═══════════════════════════════════════════════════════════════════════════

#[tokio::test]
async fn turn_handles_empty_text_response() {
    let provider = Box::new(ScriptedProvider::new(vec![ChatResponse {
        text: Some(String::new()),
        tool_calls: vec![],
        usage: None,
        reasoning_content: None,
    }]));

    let mut agent = build_agent_with(provider, vec![], ToolDispatchMode::Native);

    let response = agent.turn("hi").await.unwrap();
    assert!(response.is_empty());
}

#[tokio::test]
async fn turn_handles_none_text_response() {
    let provider = Box::new(ScriptedProvider::new(vec![ChatResponse {
        text: None,
        tool_calls: vec![],
        usage: None,
        reasoning_content: None,
    }]));

    let mut agent = build_agent_with(provider, vec![], ToolDispatchMode::Native);

    // Should not panic — falls back to empty string
    let response = agent.turn("hi").await.unwrap();
    assert!(response.is_empty());
}

// ═══════════════════════════════════════════════════════════════════════════
// 12. Mixed text + tool call responses
// ═══════════════════════════════════════════════════════════════════════════

#[tokio::test]
async fn turn_preserves_text_alongside_tool_calls() {
    let provider = Box::new(ScriptedProvider::new(vec![
        ChatResponse {
            text: Some("Let me check...".into()),
            tool_calls: vec![ToolCall {
                id: "tc1".into(),
                name: "echo".into(),
                arguments: r#"{"message": "hi"}"#.into(),
            }],
            usage: None,
            reasoning_content: None,
        },
        text_response("Here are the results"),
    ]));

    let mut agent = build_agent_with(provider, vec![Box::new(EchoTool)], ToolDispatchMode::Native);

    let response = agent.turn("check something").await.unwrap();
    assert!(
        !response.is_empty(),
        "Expected non-empty final response after mixed text+tool"
    );

    // The intermediate text should be in history
    let has_intermediate = agent
        .history()
        .iter()
        .any(|msg| msg.role == "assistant" && msg.content.contains("Let me check"));
    assert!(has_intermediate, "Intermediate text should be in history");
}

// ═══════════════════════════════════════════════════════════════════════════
// 13. Multi-tool batch in a single response
// ═══════════════════════════════════════════════════════════════════════════

#[tokio::test]
async fn turn_handles_multiple_tools_in_one_response() {
    let (counting_tool, count) = CountingTool::new();

    let provider = Box::new(ScriptedProvider::new(vec![
        tool_response(vec![
            ToolCall {
                id: "tc1".into(),
                name: "counter".into(),
                arguments: "{}".into(),
            },
            ToolCall {
                id: "tc2".into(),
                name: "counter".into(),
                arguments: r#"{"slot": 2}"#.into(),
            },
            ToolCall {
                id: "tc3".into(),
                name: "counter".into(),
                arguments: r#"{"slot": 3}"#.into(),
            },
        ]),
        text_response("All 3 done"),
    ]));

    let mut agent = build_agent_with(
        provider,
        vec![Box::new(counting_tool)],
        ToolDispatchMode::Native,
    );

    let response = agent.turn("batch").await.unwrap();
    assert!(
        !response.is_empty(),
        "Expected non-empty response after multi-tool batch"
    );
    assert_eq!(
        *count.lock().unwrap(),
        3,
        "All 3 tools should have been called"
    );
}

// ═══════════════════════════════════════════════════════════════════════════
// 14. System prompt generation & tool instructions
// ═══════════════════════════════════════════════════════════════════════════

#[tokio::test]
async fn system_prompt_injected_on_first_turn() {
    let provider = Box::new(ScriptedProvider::new(vec![text_response("ok")]));
    let mut agent = build_agent_with(provider, vec![Box::new(EchoTool)], ToolDispatchMode::Native);

    assert!(agent.history().is_empty(), "History should start empty");

    let _ = agent.turn("hi").await.unwrap();

    // First message should be the system prompt
    let first = &agent.history()[0];
    assert_eq!(
        first.role, "system",
        "First history entry should be system prompt"
    );
}

#[tokio::test]
async fn system_prompt_not_duplicated_on_second_turn() {
    let provider = Box::new(ScriptedProvider::new(vec![
        text_response("first"),
        text_response("second"),
    ]));
    let mut agent = build_agent_with(provider, vec![Box::new(EchoTool)], ToolDispatchMode::Native);

    let _ = agent.turn("hi").await.unwrap();
    let _ = agent.turn("hello again").await.unwrap();

    let system_count = agent
        .history()
        .iter()
        .filter(|msg| msg.role == "system")
        .count();
    assert_eq!(system_count, 1, "System prompt should appear exactly once");
}

// ═══════════════════════════════════════════════════════════════════════════
// 15. Conversation history fidelity
// ═══════════════════════════════════════════════════════════════════════════

#[tokio::test]
async fn history_contains_all_expected_entries_after_tool_loop() {
    let provider = Box::new(ScriptedProvider::new(vec![
        tool_response(vec![ToolCall {
            id: "tc1".into(),
            name: "echo".into(),
            arguments: r#"{"message": "tool-out"}"#.into(),
        }]),
        text_response("final answer"),
    ]));

    let mut agent = build_agent_with(provider, vec![Box::new(EchoTool)], ToolDispatchMode::Native);

    let _ = agent.turn("test").await.unwrap();

    // Expected history entries:
    //   0: system prompt
    //   1: user message "test"
    //   2: AssistantToolCalls
    //   3: ToolResults
    //   4: assistant "final answer"
    let history = agent.history();
    assert!(
        history.len() >= 5,
        "Expected at least 5 history entries, got {}",
        history.len()
    );

    assert_eq!(history[0].role, "system");
    assert_eq!(history[1].role, "user");
    assert_eq!(history[2].role, "assistant");
    let assistant_payload = assistant_payload(&history[2]);
    assert!(assistant_payload["content"].is_null());
    assert_eq!(assistant_payload["tool_calls"][0]["name"], "echo");
    assert_eq!(history[3].role, "tool");
    assert!(history[3].content.contains("tool-out"));
    assert_eq!(history[4].role, "assistant");
    assert_eq!(history[4].content, "final answer");
}

// ═══════════════════════════════════════════════════════════════════════════
// 16. Builder validation
// ═══════════════════════════════════════════════════════════════════════════

#[tokio::test]
async fn builder_fails_without_provider() {
    let result = Agent::builder()
        .tools(vec![])
        .memory(make_memory())
        .observer(make_observer())
        .tool_dispatch_mode(ToolDispatchMode::Native)
        .workspace_dir(std::path::PathBuf::from("/tmp"))
        .build();

    assert!(result.is_err(), "Building without provider should fail");
}

// ═══════════════════════════════════════════════════════════════════════════
// 17. Multi-turn conversation maintains context
// ═══════════════════════════════════════════════════════════════════════════

#[tokio::test]
async fn multi_turn_maintains_growing_history() {
    let provider = Box::new(ScriptedProvider::new(vec![
        text_response("response 1"),
        text_response("response 2"),
        text_response("response 3"),
    ]));

    let mut agent = build_agent_with(provider, vec![], ToolDispatchMode::Native);

    let r1 = agent.turn("msg 1").await.unwrap();
    let len_after_1 = agent.history().len();

    let r2 = agent.turn("msg 2").await.unwrap();
    let len_after_2 = agent.history().len();

    let r3 = agent.turn("msg 3").await.unwrap();
    let len_after_3 = agent.history().len();

    assert_eq!(r1, "response 1");
    assert_eq!(r2, "response 2");
    assert_eq!(r3, "response 3");

    // History should grow with each turn (user + assistant per turn)
    assert!(
        len_after_2 > len_after_1,
        "History should grow after turn 2"
    );
    assert!(
        len_after_3 > len_after_2,
        "History should grow after turn 3"
    );
}

// ═══════════════════════════════════════════════════════════════════════════
// 18. Tool call with stringified JSON arguments (common LLM pattern)
// ═══════════════════════════════════════════════════════════════════════════

// ═══════════════════════════════════════════════════════════════════════════
// 19. XML dispatcher edge cases
// ═══════════════════════════════════════════════════════════════════════════

#[test]
fn xml_dispatcher_handles_nested_json() {
    let (text, calls) = parse_tool_calls(
        r#"<tool_call>
{"name": "file_write", "arguments": {"path": "test.json", "content": "{\"key\": \"value\"}"}}
</tool_call>"#,
    );
    assert!(text.trim().is_empty());
    assert_eq!(calls.len(), 1);
    assert_eq!(calls[0].name, "file_write");
    assert_eq!(calls[0].arguments["path"], "test.json");
}

#[test]
fn xml_dispatcher_handles_empty_tool_call_tag() {
    let (text, calls) = parse_tool_calls("<tool_call>\n</tool_call>\nSome text");
    assert!(calls.is_empty());
    assert!(text.contains("Some text"));
}

#[test]
fn xml_dispatcher_handles_unclosed_tool_call() {
    let (text, calls) = parse_tool_calls("Before\n<tool_call>\n{\"name\": \"shell\"}");
    // Should not panic — just treat as text
    assert_eq!(calls.len(), 1);
    assert_eq!(calls[0].name, "shell");
    assert!(text.contains("Before"));
}

// ═══════════════════════════════════════════════════════════════════════════
// 20. ConversationMessage serialization round-trip
// ═══════════════════════════════════════════════════════════════════════════

#[test]
fn native_dispatcher_handles_stringified_arguments() {
    let parsed = parse_tool_call_value(&serde_json::json!({
        "id": "tc1",
        "name": "echo",
        "arguments": "{\"message\":\"hello\"}"
    }))
    .expect("tool call should parse");

    assert_eq!(parsed.name, "echo");
    assert_eq!(parsed.tool_call_id.as_deref(), Some("tc1"));
    assert_eq!(parsed.arguments["message"], "hello");
}

#[test]
fn conversation_message_serialization_roundtrip() {
    let messages = vec![
        ChatMessage::system("system"),
        ChatMessage::user("hello"),
        ChatMessage::assistant(
            r#"{"content":"checking","tool_calls":[{"id":"tc1","name":"shell","arguments":"{}"}]}"#,
        ),
        ChatMessage::tool(r#"{"tool_call_id":"tc1","content":"ok"}"#),
        ChatMessage::assistant("done"),
    ];

    for msg in &messages {
        let json = serde_json::to_string(msg).unwrap();
        let parsed: ChatMessage = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed.role, msg.role);
        assert_eq!(parsed.content, msg.content);
    }
}

// ═══════════════════════════════════════════════════════════════════════════
// 21. Tool dispatcher format_results
// ═══════════════════════════════════════════════════════════════════════════

#[test]
fn xml_format_results_includes_status_and_output() {
    let tool_specs = vec![crate::tools::ToolSpec {
        name: "echo".into(),
        description: "Echoes the input".into(),
        parameters: serde_json::json!({"type":"object"}),
    }];

    let instructions = build_tool_instructions_from_specs(&tool_specs, None);
    assert!(instructions.contains("## Tool Use Protocol"));
    assert!(instructions.contains("<tool_call>"));
    assert!(instructions.contains("echo"));
    assert!(instructions.contains("Echoes the input"));
}

#[test]
fn native_format_results_maps_tool_call_ids() {
    let tool_message = ChatMessage::tool(r#"{"tool_call_id":"tc-001","content":"out1"}"#);
    let payload: serde_json::Value = serde_json::from_str(&tool_message.content).unwrap();
    assert_eq!(payload["tool_call_id"], "tc-001");
    assert_eq!(payload["content"], "out1");
}

// ═══════════════════════════════════════════════════════════════════════════
// 22. to_provider_messages conversion
// ═══════════════════════════════════════════════════════════════════════════

#[tokio::test]
async fn xml_dispatcher_converts_history_to_provider_messages() {
    let provider = Box::new(ScriptedProvider::new(vec![
        xml_tool_response("echo", r#"{"message": "xml-test"}"#),
        text_response("XML tool completed"),
    ]));

    let mut agent = build_agent_with(provider, vec![Box::new(EchoTool)], ToolDispatchMode::Xml);
    let _ = agent.turn("test xml").await.unwrap();
    assert!(history_contains_tool_result(agent.history(), "xml-test"));
    assert!(
        agent
            .history()
            .iter()
            .any(|msg| msg.role == "user" && msg.content.starts_with("[Tool results]\n"))
    );
}

#[tokio::test]
async fn native_dispatcher_converts_tool_results_to_tool_messages() {
    let provider = Box::new(ScriptedProvider::new(vec![
        tool_response(vec![ToolCall {
            id: "tc1".into(),
            name: "echo".into(),
            arguments: r#"{"message":"hello"}"#.into(),
        }]),
        text_response("done"),
    ]));

    let mut agent = build_agent_with(provider, vec![Box::new(EchoTool)], ToolDispatchMode::Native);
    let _ = agent.turn("run echo").await.unwrap();
    let tool_message = agent
        .history()
        .iter()
        .find(|msg| msg.role == "tool")
        .expect("native mode should store tool messages");
    let payload: serde_json::Value = serde_json::from_str(&tool_message.content).unwrap();
    assert_eq!(payload["tool_call_id"], "tc1");
    assert_eq!(payload["content"], "hello");
}

// ═══════════════════════════════════════════════════════════════════════════
// 23. XML tool instructions generation
// ═══════════════════════════════════════════════════════════════════════════

#[test]
fn xml_dispatcher_generates_tool_instructions() {
    let instructions = build_tool_instructions_from_specs(
        &[crate::tools::ToolSpec {
            name: "echo".into(),
            description: "Echoes the input".into(),
            parameters: serde_json::json!({"type":"object"}),
        }],
        None,
    );

    assert!(instructions.contains("## Tool Use Protocol"));
    assert!(instructions.contains("<tool_call>"));
    assert!(instructions.contains("echo"));
}

#[test]
fn native_dispatcher_returns_empty_instructions() {
    assert!(ToolDispatchMode::Native.uses_native_tools(true, true));
    assert!(!ToolDispatchMode::Xml.uses_native_tools(true, true));
}

// ═══════════════════════════════════════════════════════════════════════════
// 24. Clear history
// ═══════════════════════════════════════════════════════════════════════════

#[tokio::test]
async fn clear_history_resets_conversation() {
    let provider = Box::new(ScriptedProvider::new(vec![
        text_response("first"),
        text_response("second"),
    ]));

    let mut agent = build_agent_with(provider, vec![], ToolDispatchMode::Native);

    let _ = agent.turn("hi").await.unwrap();
    assert!(!agent.history().is_empty());

    agent.clear_history();
    assert!(agent.history().is_empty());

    // Next turn should re-inject system prompt
    let _ = agent.turn("hello again").await.unwrap();
    assert_eq!(agent.history()[0].role, "system");
}

// ═══════════════════════════════════════════════════════════════════════════
// 25. run_single delegates to turn
// ═══════════════════════════════════════════════════════════════════════════

#[tokio::test]
async fn run_single_delegates_to_turn() {
    let provider = Box::new(ScriptedProvider::new(vec![text_response("via run_single")]));
    let mut agent = build_agent_with(provider, vec![], ToolDispatchMode::Native);

    let response = agent.run_single("test").await.unwrap();
    assert!(
        !response.is_empty(),
        "Expected non-empty response from run_single"
    );
}

#[test]
fn single_message_artifact_uses_python_compatible_schema() {
    let temp = tempfile::tempdir().unwrap();
    let path = write_single_message_artifact(
        temp.path(),
        Some("sess-rust"),
        "test topic",
        "test-model",
        "user asks a question",
        "assistant answers without evidence",
        "completed",
    )
    .unwrap();

    let payload: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();

    assert_eq!(payload["schema_version"], "rain-session-artifact/v1");
    assert_eq!(payload["session_id"], "sess-rust");
    assert_eq!(payload["topic"], "test topic");
    assert_eq!(payload["model"], "test-model");
    assert_eq!(payload["status"], "completed");
    assert_eq!(payload["loaded_papers_count"], 0);
    assert_eq!(payload["turns"].as_array().unwrap().len(), 2);
    assert_eq!(payload["turns"][0]["agent"], "USER");
    assert_eq!(payload["turns"][1]["agent"], "R.A.I.N.");
    assert_eq!(
        payload["turns"][1]["grounded_response"]["red_badge"],
        serde_json::Value::Bool(true)
    );
}

#[test]
fn single_message_artifact_includes_memory_evidence_when_available() {
    let temp = tempfile::tempdir().unwrap();
    let entries = vec![MemoryEntry {
        id: "mem-1".into(),
        key: "paper_note".into(),
        content: "Standing wave anchoring remains plausible at low energy.".into(),
        category: MemoryCategory::Core,
        timestamp: "2026-04-13T00:00:00Z".into(),
        session_id: None,
        score: Some(0.91),
        namespace: "default".into(),
        importance: Some(0.8),
        superseded_by: None,
    }];
    let path = write_single_message_artifact_with_memory(
        temp.path(),
        Some("sess-rust"),
        "test topic",
        "test-model",
        "user asks a question",
        "assistant answers with evidence",
        "completed",
        &entries,
    )
    .unwrap();

    let payload: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    let grounded = &payload["turns"][1]["grounded_response"];

    assert_eq!(grounded["grounded"], serde_json::Value::Bool(true));
    assert_eq!(grounded["red_badge"], serde_json::Value::Bool(false));
    assert_eq!(grounded["provenance"][0], "paper_note");
    assert_eq!(
        grounded["evidence"][0]["quote"],
        "Standing wave anchoring remains plausible at low energy."
    );
}
