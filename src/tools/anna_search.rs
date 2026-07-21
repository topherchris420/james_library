//! Anna agent search tool — hybrid engineering-knowledge retrieval.
//!
//! Client for the Anna engine's LLM-agent endpoint
//! (`POST /api/v1/agent/search`, <https://github.com/topherchris420/anna>):
//! hybrid BM25 + semantic search over papers, standards, code, and datasheets,
//! returning flat citation-ready snippets with relevance scores normalized to
//! 0–1. The wire contract is pinned by the OpenAPI spec the server ships
//! (`docs/openapi-agent-search.json`, served live at
//! `GET /api/v1/agent/openapi.json`); success and error responses share one
//! envelope, so a single struct deserializes both.

use super::traits::{Tool, ToolResult};
use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::time::Duration;

const CONNECT_TIMEOUT_SECS: u64 = 10;
/// Server-side clamp bounds for `limit` (mirrors the OpenAPI spec).
const MAX_LIMIT: usize = 25;

// ── Wire contract (docs/openapi-agent-search.json) ────────────────────────────

#[derive(Debug, Serialize)]
struct AgentSearchRequest {
    query: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    domain_filter: Option<String>,
    limit: usize,
    min_score: f64,
}

#[derive(Debug, Deserialize)]
struct AgentSearchResponse {
    /// "success" or "error".
    status: String,
    /// Set when `status == "error"`.
    #[serde(default)]
    error: Option<String>,
    #[serde(default)]
    query: Option<String>,
    #[serde(default)]
    total_results: u32,
    #[serde(default)]
    results: Vec<AgentSearchResult>,
}

#[derive(Debug, Deserialize)]
struct AgentSearchResult {
    id: String,
    title: String,
    #[serde(default)]
    authors: Vec<String>,
    #[serde(default)]
    content_chunk: String,
    #[serde(default)]
    source_url: String,
    relevance_score: f64,
    #[serde(default)]
    source: String,
    #[serde(default)]
    kind: String,
    #[serde(default)]
    published: Option<String>,
}

// ── Tool struct ───────────────────────────────────────────────────────────────

/// Searches an Anna deployment's knowledge index for the agent.
pub struct AnnaSearchTool {
    base_url: String,
    default_limit: usize,
    default_min_score: f64,
    timeout_secs: u64,
}

impl AnnaSearchTool {
    pub fn new(
        base_url: String,
        default_limit: usize,
        default_min_score: f64,
        timeout_secs: u64,
    ) -> Self {
        Self {
            base_url: base_url.trim().trim_end_matches('/').to_string(),
            default_limit: default_limit.clamp(1, MAX_LIMIT),
            default_min_score: default_min_score.clamp(0.0, 1.0),
            timeout_secs: timeout_secs.max(1),
        }
    }

    fn endpoint_url(&self) -> String {
        format!("{}/api/v1/agent/search", self.base_url)
    }

    async fn fetch(&self, request: &AgentSearchRequest) -> anyhow::Result<AgentSearchResponse> {
        let builder = reqwest::Client::builder()
            .timeout(Duration::from_secs(self.timeout_secs))
            .connect_timeout(Duration::from_secs(CONNECT_TIMEOUT_SECS))
            .user_agent("R.A.I.N.-anna-search/1.0");
        let builder = crate::config::apply_runtime_proxy_to_builder(builder, "tool.anna_search");
        let client = builder.build()?;

        let response = client
            .post(self.endpoint_url())
            .json(request)
            .send()
            .await
            .map_err(|e| {
                anyhow::anyhow!(
                    "Could not reach Anna at {}: {e}. Check [anna_search] base_url.",
                    self.base_url
                )
            })?;

        let status = response.status();
        let body = response.text().await?;

        // Anna returns its error envelope with 400/503 bodies too, so parse
        // before checking the HTTP status to surface the server's own message.
        match serde_json::from_str::<AgentSearchResponse>(&body) {
            Ok(parsed) => Ok(parsed),
            Err(e) if status.is_success() => {
                anyhow::bail!("Failed to parse Anna response: {e}")
            }
            Err(_) => anyhow::bail!("Anna returned HTTP {status} with a non-JSON body"),
        }
    }

    /// Render the response as compact, citation-ready text for the LLM.
    fn format_output(response: &AgentSearchResponse, min_score: f64) -> String {
        let query = response.query.as_deref().unwrap_or("");
        if response.results.is_empty() {
            return format!(
                "No results for: {query} (min_score {min_score}). \
                 Try a lower min_score, a broader query, or no domain_filter."
            );
        }

        let mut lines = vec![format!(
            "Anna search results for: {query} ({} shown)",
            response.total_results
        )];
        for (i, result) in response.results.iter().enumerate() {
            lines.push(format!(
                "{}. [{:.2}] {}{} ({}{}{})",
                i + 1,
                result.relevance_score,
                result.title,
                format_authors(&result.authors),
                result.source,
                if result.kind.is_empty() { "" } else { " " },
                result.kind,
            ));
            if !result.source_url.is_empty() {
                lines.push(format!("   {}", result.source_url));
            }
            let published = result.published.as_deref().unwrap_or("");
            lines.push(format!(
                "   id: {}{}",
                result.id,
                if published.is_empty() {
                    String::new()
                } else {
                    format!(" | published: {published}")
                }
            ));
            if !result.content_chunk.is_empty() {
                lines.push(format!("   {}", result.content_chunk));
            }
        }
        lines.join("\n")
    }
}

fn format_authors(authors: &[String]) -> String {
    if authors.is_empty() {
        return String::new();
    }
    let shown: Vec<&str> = authors.iter().take(3).map(String::as_str).collect();
    let suffix = if authors.len() > 3 { " et al." } else { "" };
    format!(" — {}{suffix}", shown.join(", "))
}

// ── Tool trait ────────────────────────────────────────────────────────────────

#[async_trait]
impl Tool for AnnaSearchTool {
    fn name(&self) -> &str {
        "anna_search"
    }

    fn description(&self) -> &str {
        "Search the Anna engineering knowledge index (papers, standards, code, \
         datasheets) with hybrid keyword + semantic retrieval. Returns \
         citation-ready snippets with source URLs and 0-1 relevance scores. \
         Use domain_filter to narrow to a source ('arxiv'), a document kind \
         ('paper'), or a category ('category:cs.RO')."
    }

    fn parameters_schema(&self) -> Value {
        // Mirrors components.schemas.AgentSearchRequest in the server's
        // OpenAPI spec (docs/openapi-agent-search.json).
        json!({
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search string or academic query."
                },
                "domain_filter": {
                    "type": "string",
                    "description": "Optional filter: a source ('arxiv', 'github', 'nasa'), \
                                    a document kind ('paper', 'report', 'standard', \
                                    'repository', 'code', 'documentation', 'datasheet'), \
                                    or a prefixed facet ('source:arxiv', 'kind:paper', \
                                    'category:cs.RO'). Unknown values match nothing."
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 25,
                    "description": "Maximum number of results (default from config, usually 5)."
                },
                "min_score": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "description": "Drop results below this 0-1 relevance (default 0.0). \
                                    1.0 means top-ranked by every retriever."
                }
            },
            "required": ["query"]
        })
    }

    async fn execute(&self, args: Value) -> anyhow::Result<ToolResult> {
        let query = match args.get("query").and_then(Value::as_str) {
            Some(q) if !q.trim().is_empty() => q.trim().to_string(),
            _ => {
                return Ok(ToolResult {
                    success: false,
                    output: String::new(),
                    error: Some("Missing required parameter 'query'".into()),
                });
            }
        };

        let domain_filter = args
            .get("domain_filter")
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(ToOwned::to_owned);

        let limit = args
            .get("limit")
            .and_then(Value::as_u64)
            .map_or(self.default_limit, |l| {
                usize::try_from(l).unwrap_or(MAX_LIMIT).clamp(1, MAX_LIMIT)
            });

        let min_score = args
            .get("min_score")
            .and_then(Value::as_f64)
            .map_or(self.default_min_score, |s| s.clamp(0.0, 1.0));

        let request = AgentSearchRequest {
            query,
            domain_filter,
            limit,
            min_score,
        };

        match self.fetch(&request).await {
            Ok(response) if response.status == "success" => Ok(ToolResult {
                success: true,
                output: Self::format_output(&response, min_score),
                error: None,
            }),
            Ok(response) => Ok(ToolResult {
                success: false,
                output: String::new(),
                error: Some(
                    response
                        .error
                        .unwrap_or_else(|| format!("Anna returned status '{}'", response.status)),
                ),
            }),
            Err(e) => Ok(ToolResult {
                success: false,
                output: String::new(),
                error: Some(e.to_string()),
            }),
        }
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn make_tool() -> AnnaSearchTool {
        AnnaSearchTool::new("http://localhost:8000".into(), 5, 0.0, 15)
    }

    fn success_body() -> &'static str {
        r#"{
            "status": "success",
            "query": "kalman filter divergence",
            "total_results": 2,
            "results": [
                {
                    "id": "arxiv:8c4f01f9a3b2d715",
                    "title": "Kalman Filter Divergence Analysis",
                    "authors": ["A. Author", "B. Author", "C. Author", "D. Author"],
                    "content_chunk": "the Kalman gain saturates and the filter diverges",
                    "source_url": "https://arxiv.org/abs/2401.00001",
                    "relevance_score": 0.92,
                    "source": "arxiv",
                    "kind": "paper",
                    "published": "2024-01-15"
                },
                {
                    "id": "github:aaaa",
                    "title": "ekf-rs",
                    "authors": [],
                    "content_chunk": "Rust EKF implementation",
                    "source_url": "",
                    "relevance_score": 0.41,
                    "source": "github",
                    "kind": "repository",
                    "published": null
                }
            ]
        }"#
    }

    #[test]
    fn test_tool_name_and_schema() {
        let tool = make_tool();
        assert_eq!(tool.name(), "anna_search");
        let schema = tool.parameters_schema();
        assert_eq!(schema["type"], "object");
        assert_eq!(schema["required"], json!(["query"]));
        assert!(schema["properties"]["domain_filter"].is_object());
        assert_eq!(schema["properties"]["limit"]["maximum"], 25);
    }

    #[test]
    fn test_endpoint_url_strips_trailing_slash() {
        let tool = AnnaSearchTool::new("https://anna.example.com/".into(), 5, 0.0, 15);
        assert_eq!(
            tool.endpoint_url(),
            "https://anna.example.com/api/v1/agent/search"
        );
    }

    #[test]
    fn test_constructor_clamps_config_values() {
        let tool = AnnaSearchTool::new("http://x".into(), 999, 7.5, 0);
        assert_eq!(tool.default_limit, MAX_LIMIT);
        assert_eq!(tool.default_min_score, 1.0);
        assert_eq!(tool.timeout_secs, 1);
    }

    #[test]
    fn test_request_serialization_omits_absent_domain_filter() {
        let request = AgentSearchRequest {
            query: "dma".into(),
            domain_filter: None,
            limit: 5,
            min_score: 0.0,
        };
        let value = serde_json::to_value(&request).unwrap();
        assert!(value.get("domain_filter").is_none());
        assert_eq!(value["query"], "dma");
        assert_eq!(value["limit"], 5);
    }

    #[test]
    fn test_parse_and_format_success_response() {
        let response: AgentSearchResponse = serde_json::from_str(success_body()).unwrap();
        assert_eq!(response.status, "success");
        assert_eq!(response.total_results, 2);

        let output = AnnaSearchTool::format_output(&response, 0.0);
        assert!(output.contains("Anna search results for: kalman filter divergence"));
        assert!(output.contains("1. [0.92] Kalman Filter Divergence Analysis"));
        // Four authors collapse to three plus "et al."
        assert!(output.contains("A. Author, B. Author, C. Author et al."));
        assert!(output.contains("https://arxiv.org/abs/2401.00001"));
        assert!(output.contains("id: arxiv:8c4f01f9a3b2d715 | published: 2024-01-15"));
        // Second hit has no URL and no published date; the id line still shows.
        assert!(output.contains("2. [0.41] ekf-rs (github repository)"));
        assert!(output.contains("id: github:aaaa\n"));
    }

    #[test]
    fn test_parse_error_envelope() {
        let body = r#"{
            "status": "error",
            "error": "'query' is required and must be a non-empty string",
            "total_results": 0,
            "results": []
        }"#;
        let response: AgentSearchResponse = serde_json::from_str(body).unwrap();
        assert_eq!(response.status, "error");
        assert_eq!(
            response.error.as_deref(),
            Some("'query' is required and must be a non-empty string")
        );
        assert!(response.results.is_empty());
    }

    #[test]
    fn test_format_output_empty_results_gives_guidance() {
        let response: AgentSearchResponse = serde_json::from_str(
            r#"{"status":"success","query":"x","total_results":0,"results":[]}"#,
        )
        .unwrap();
        let output = AnnaSearchTool::format_output(&response, 0.8);
        assert!(output.contains("No results for: x"));
        assert!(output.contains("min_score 0.8"));
    }

    #[tokio::test]
    async fn test_execute_missing_query_fails_cleanly() {
        let tool = make_tool();
        let result = tool.execute(json!({})).await.unwrap();
        assert!(!result.success);
        assert!(result.error.unwrap().contains("query"));
    }

    #[tokio::test]
    async fn test_execute_blank_query_fails_cleanly() {
        let tool = make_tool();
        let result = tool.execute(json!({"query": "   "})).await.unwrap();
        assert!(!result.success);
    }

    #[tokio::test]
    async fn test_execute_unreachable_server_reports_base_url() {
        // Port 9 (discard) is never an Anna server; connection must fail fast
        // and the error must point at the configured base_url.
        let tool = AnnaSearchTool::new("http://127.0.0.1:9".into(), 5, 0.0, 2);
        let result = tool.execute(json!({"query": "kalman"})).await.unwrap();
        assert!(!result.success);
        assert!(result.error.unwrap().contains("http://127.0.0.1:9"));
    }
}
