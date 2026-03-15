use super::traits::{Tool, ToolResult};
use async_trait::async_trait;
use serde::Deserialize;
use serde_json::json;
use std::sync::Arc;
use std::time::Duration;

use crate::security::SecurityPolicy;

/// Maximum response body size from ArXiv API (2 MB).
const MAX_RESPONSE_BYTES: usize = 2 * 1024 * 1024;
/// Abstract truncation length in formatted output.
const ABSTRACT_TRUNCATE_LEN: usize = 500;
/// ArXiv API base URL (hardcoded for SSRF safety).
const ARXIV_API_URL: &str = "https://export.arxiv.org/api/query";

/// Tool for searching academic papers on ArXiv.org.
///
/// Queries the ArXiv API and returns structured paper metadata including
/// titles, authors, abstracts, URLs, and categories. Useful for novelty
/// verification and external grounding of research claims.
pub struct ArxivSearchTool {
    security: Arc<SecurityPolicy>,
    max_results: usize,
    timeout: Duration,
}

impl ArxivSearchTool {
    pub fn new(security: Arc<SecurityPolicy>, max_results: usize, timeout_secs: u64) -> Self {
        Self {
            security,
            max_results: max_results.clamp(1, 100),
            timeout: Duration::from_secs(timeout_secs.max(1)),
        }
    }
}

// ── Atom XML deserialization structs ────────────────────────────

#[derive(Debug, Deserialize)]
struct AtomFeed {
    #[serde(rename = "entry", default)]
    entries: Vec<AtomEntry>,
}

#[derive(Debug, Deserialize)]
struct AtomEntry {
    #[serde(default)]
    title: String,
    #[serde(default)]
    summary: String,
    #[serde(default)]
    id: String,
    #[serde(default)]
    published: String,
    #[serde(default)]
    updated: String,
    #[serde(rename = "author", default)]
    authors: Vec<AtomAuthor>,
    #[serde(rename = "link", default)]
    links: Vec<AtomLink>,
    #[serde(rename = "category", default)]
    categories: Vec<AtomCategory>,
}

#[derive(Debug, Deserialize)]
struct AtomAuthor {
    #[serde(default)]
    name: String,
}

#[derive(Debug, Deserialize)]
struct AtomLink {
    #[serde(rename = "@href", default)]
    href: String,
    #[serde(rename = "@title", default)]
    title: Option<String>,
}

#[derive(Debug, Deserialize)]
struct AtomCategory {
    #[serde(rename = "@term", default)]
    term: String,
}

// ── Clean intermediate type ─────────────────────────────────────

#[derive(Debug)]
struct ArxivPaper {
    title: String,
    authors: Vec<String>,
    abstract_text: String,
    arxiv_url: String,
    pdf_url: Option<String>,
    categories: Vec<String>,
    published: String,
    updated: String,
}

// ── Parsing ─────────────────────────────────────────────────────

fn parse_arxiv_response(xml: &str) -> anyhow::Result<Vec<ArxivPaper>> {
    let feed: AtomFeed = quick_xml::de::from_str(xml)
        .map_err(|e| anyhow::anyhow!("Failed to parse ArXiv Atom response: {e}"))?;

    let papers = feed
        .entries
        .into_iter()
        .map(|entry| {
            let pdf_url = entry
                .links
                .iter()
                .find(|l| l.title.as_deref() == Some("pdf"))
                .map(|l| l.href.clone());

            // Normalise whitespace in title and abstract (ArXiv injects newlines)
            let title = normalise_whitespace(&entry.title);
            let abstract_text = normalise_whitespace(&entry.summary);

            ArxivPaper {
                title,
                authors: entry.authors.into_iter().map(|a| a.name).collect(),
                abstract_text,
                arxiv_url: entry.id,
                pdf_url,
                categories: entry.categories.into_iter().map(|c| c.term).collect(),
                published: entry.published,
                updated: entry.updated,
            }
        })
        .collect();

    Ok(papers)
}

fn normalise_whitespace(s: &str) -> String {
    s.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn format_results(papers: &[ArxivPaper], query: &str) -> String {
    if papers.is_empty() {
        return format!("No results found for: {query}");
    }

    let mut lines = vec![format!(
        "ArXiv search results for: {query} ({} result{})",
        papers.len(),
        if papers.len() == 1 { "" } else { "s" }
    )];

    for (i, paper) in papers.iter().enumerate() {
        lines.push(String::new());
        lines.push(format!("[{}] {}", i + 1, paper.title));
        if !paper.authors.is_empty() {
            lines.push(format!("    Authors: {}", paper.authors.join(", ")));
        }
        lines.push(format!(
            "    Published: {}{}",
            truncate_date(&paper.published),
            if paper.updated == paper.published {
                String::new()
            } else {
                format!(" | Updated: {}", truncate_date(&paper.updated))
            }
        ));
        if !paper.categories.is_empty() {
            lines.push(format!("    Categories: {}", paper.categories.join(", ")));
        }
        lines.push(format!("    URL: {}", paper.arxiv_url));
        if let Some(pdf) = &paper.pdf_url {
            lines.push(format!("    PDF: {pdf}"));
        }
        let abs = if paper.abstract_text.len() > ABSTRACT_TRUNCATE_LEN {
            let mut end = ABSTRACT_TRUNCATE_LEN;
            while end > 0 && !paper.abstract_text.is_char_boundary(end) {
                end -= 1;
            }
            format!("{}...", &paper.abstract_text[..end])
        } else {
            paper.abstract_text.clone()
        };
        if !abs.is_empty() {
            lines.push(format!("    Abstract: {abs}"));
        }
    }

    lines.join("\n")
}

/// Trim ISO timestamp to date only (YYYY-MM-DD).
fn truncate_date(ts: &str) -> &str {
    ts.get(..10).unwrap_or(ts)
}

// ── Tool trait impl ─────────────────────────────────────────────

#[async_trait]
impl Tool for ArxivSearchTool {
    fn name(&self) -> &str {
        "arxiv_search"
    }

    fn description(&self) -> &str {
        "Search ArXiv for academic papers by query, author, or category. \
         Returns paper titles, authors, abstracts, URLs, and categories. \
         Supports ArXiv field prefixes: ti: (title), au: (author), \
         abs: (abstract), cat: (category), all: (all fields). \
         Use AND/OR/ANDNOT for boolean logic."
    }

    fn parameters_schema(&self) -> serde_json::Value {
        json!({
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query. Supports ArXiv field prefixes: ti: (title), au: (author), abs: (abstract), cat: (category), all: (all fields). Use AND/OR/ANDNOT for boolean logic. Examples: 'ti:attention AND cat:cs.AI', 'au:bengio', 'all:transformer'"
                },
                "max_results": {
                    "type": "integer",
                    "description": "Number of results to return (1–100). Defaults to tool configuration value."
                },
                "start": {
                    "type": "integer",
                    "description": "Offset for pagination (0-based). Default: 0."
                }
            },
            "required": ["query"]
        })
    }

    async fn execute(&self, args: serde_json::Value) -> anyhow::Result<ToolResult> {
        // ── Parameter extraction ────────────────────────────────
        let query = args
            .get("query")
            .and_then(|q| q.as_str())
            .ok_or_else(|| anyhow::anyhow!("Missing required parameter: query"))?;

        if query.trim().is_empty() {
            return Ok(ToolResult {
                success: false,
                output: String::new(),
                error: Some("Search query cannot be empty".into()),
            });
        }

        let max_results = args
            .get("max_results")
            .and_then(serde_json::Value::as_u64)
            .map(|v| usize::try_from(v).unwrap_or(usize::MAX).clamp(1, 100))
            .unwrap_or(self.max_results);

        let start = args
            .get("start")
            .and_then(serde_json::Value::as_u64)
            .unwrap_or(0);

        // ── Security checks ─────────────────────────────────────
        if !self.security.can_act() {
            return Ok(ToolResult {
                success: false,
                output: String::new(),
                error: Some("Action blocked: autonomy is read-only".into()),
            });
        }

        if !self.security.record_action() {
            return Ok(ToolResult {
                success: false,
                output: String::new(),
                error: Some("Action blocked: rate limit exceeded".into()),
            });
        }

        // ── Build request ───────────────────────────────────────
        let encoded_query = urlencoding::encode(query);
        let url = format!(
            "{ARXIV_API_URL}?search_query={encoded_query}&start={start}&max_results={max_results}"
        );

        tracing::info!("ArXiv search: query={query}, max_results={max_results}, start={start}");

        let builder = reqwest::Client::builder()
            .timeout(self.timeout)
            .connect_timeout(Duration::from_secs(10))
            .user_agent("ZeroClaw/0.1 (arxiv_search tool)");
        let builder = crate::config::apply_runtime_proxy_to_builder(builder, "tool.arxiv_search");
        let client = builder.build()?;

        // ── Execute request ─────────────────────────────────────
        let response = client
            .get(&url)
            .send()
            .await
            .map_err(|e| anyhow::anyhow!("ArXiv API request failed: {e}"))?;

        if !response.status().is_success() {
            return Ok(ToolResult {
                success: false,
                output: String::new(),
                error: Some(format!("ArXiv API returned HTTP {}", response.status())),
            });
        }

        // Read body with size guard
        let body = response
            .bytes()
            .await
            .map_err(|e| anyhow::anyhow!("Failed to read ArXiv response body: {e}"))?;

        if body.len() > MAX_RESPONSE_BYTES {
            return Ok(ToolResult {
                success: false,
                output: String::new(),
                error: Some(format!(
                    "ArXiv response too large ({} bytes, max {MAX_RESPONSE_BYTES})",
                    body.len()
                )),
            });
        }

        let xml = String::from_utf8_lossy(&body);

        // ── Parse and format ────────────────────────────────────
        let papers = parse_arxiv_response(&xml)?;
        let output = format_results(&papers, query);

        Ok(ToolResult {
            success: true,
            output,
            error: None,
        })
    }
}

// ── Tests ───────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::security::{AutonomyLevel, SecurityPolicy};

    fn test_security() -> Arc<SecurityPolicy> {
        Arc::new(SecurityPolicy::default())
    }

    fn test_tool() -> ArxivSearchTool {
        ArxivSearchTool::new(test_security(), 10, 30)
    }

    #[test]
    fn tool_name() {
        assert_eq!(test_tool().name(), "arxiv_search");
    }

    #[test]
    fn tool_description_nonempty() {
        assert!(!test_tool().description().is_empty());
    }

    #[test]
    fn parameters_schema_requires_query() {
        let schema = test_tool().parameters_schema();
        let required = schema["required"].as_array().unwrap();
        assert!(required.iter().any(|v| v.as_str() == Some("query")));
    }

    #[test]
    fn constructor_clamps_max_results() {
        let tool = ArxivSearchTool::new(test_security(), 0, 30);
        assert_eq!(tool.max_results, 1);

        let tool = ArxivSearchTool::new(test_security(), 200, 30);
        assert_eq!(tool.max_results, 100);

        let tool = ArxivSearchTool::new(test_security(), 50, 30);
        assert_eq!(tool.max_results, 50);
    }

    #[test]
    fn constructor_clamps_timeout() {
        let tool = ArxivSearchTool::new(test_security(), 10, 0);
        assert_eq!(tool.timeout, Duration::from_secs(1));
    }

    #[tokio::test]
    async fn execute_rejects_missing_query() {
        let tool = test_tool();
        let result = tool.execute(json!({})).await;
        assert!(result.is_err());
    }

    #[tokio::test]
    async fn execute_rejects_empty_query() {
        let tool = test_tool();
        let result = tool.execute(json!({"query": "  "})).await.unwrap();
        assert!(!result.success);
        assert!(result.error.unwrap().contains("empty"));
    }

    #[test]
    fn parse_atom_feed_with_entries() {
        let xml = r#"<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.12345v1</id>
    <title>Attention Is All You Need</title>
    <summary>We propose a new architecture based on attention mechanisms.</summary>
    <published>2024-01-15T00:00:00Z</published>
    <updated>2024-01-16T00:00:00Z</updated>
    <author><name>Alice Researcher</name></author>
    <author><name>Bob Scientist</name></author>
    <link href="http://arxiv.org/abs/2401.12345v1" rel="alternate" type="text/html"/>
    <link href="http://arxiv.org/pdf/2401.12345v1" title="pdf" type="application/pdf"/>
    <category term="cs.AI" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.CL" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
</feed>"#;
        let papers = parse_arxiv_response(xml).unwrap();
        assert_eq!(papers.len(), 1);
        let p = &papers[0];
        assert_eq!(p.title, "Attention Is All You Need");
        assert_eq!(p.authors, vec!["Alice Researcher", "Bob Scientist"]);
        assert_eq!(
            p.abstract_text,
            "We propose a new architecture based on attention mechanisms."
        );
        assert_eq!(p.arxiv_url, "http://arxiv.org/abs/2401.12345v1");
        assert_eq!(
            p.pdf_url.as_deref(),
            Some("http://arxiv.org/pdf/2401.12345v1")
        );
        assert_eq!(p.categories, vec!["cs.AI", "cs.CL"]);
        assert_eq!(p.published, "2024-01-15T00:00:00Z");
        assert_eq!(p.updated, "2024-01-16T00:00:00Z");
    }

    #[test]
    fn parse_atom_feed_empty_results() {
        let xml = r#"<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
</feed>"#;
        let papers = parse_arxiv_response(xml).unwrap();
        assert!(papers.is_empty());
    }

    #[test]
    fn parse_atom_feed_malformed() {
        let result = parse_arxiv_response("<not-valid-xml");
        assert!(result.is_err());
    }

    #[test]
    fn format_results_empty() {
        let output = format_results(&[], "test query");
        assert!(output.contains("No results found"));
    }

    #[test]
    fn format_results_truncates_long_abstract() {
        let paper = ArxivPaper {
            title: "Test Paper".into(),
            authors: vec!["Author A".into()],
            abstract_text: "x".repeat(600),
            arxiv_url: "http://arxiv.org/abs/0000.00000".into(),
            pdf_url: None,
            categories: vec!["cs.AI".into()],
            published: "2024-01-01T00:00:00Z".into(),
            updated: "2024-01-01T00:00:00Z".into(),
        };
        let output = format_results(&[paper], "test");
        // The abstract line should end with "..." and be truncated
        let abstract_line = output.lines().find(|l| l.contains("Abstract:")).unwrap();
        assert!(abstract_line.ends_with("..."));
        // Should be truncated to ~500 chars + prefix + "..."
        assert!(abstract_line.len() < 600);
    }

    #[test]
    fn normalise_whitespace_collapses() {
        assert_eq!(normalise_whitespace("  hello\n  world  "), "hello world");
    }

    #[test]
    fn truncate_date_works() {
        assert_eq!(truncate_date("2024-01-15T00:00:00Z"), "2024-01-15");
        assert_eq!(truncate_date("short"), "short");
    }

    #[test]
    fn spec_generation() {
        let tool = test_tool();
        let spec = tool.spec();
        assert_eq!(spec.name, "arxiv_search");
        assert!(!spec.description.is_empty());
        assert!(spec.parameters.is_object());
    }

    #[tokio::test]
    async fn readonly_security_blocks_execution() {
        let security = Arc::new(SecurityPolicy {
            autonomy: AutonomyLevel::ReadOnly,
            ..SecurityPolicy::default()
        });
        let tool = ArxivSearchTool::new(security, 10, 30);
        let result = tool.execute(json!({"query": "test"})).await.unwrap();
        assert!(!result.success);
        assert!(result.error.unwrap().contains("read-only"));
    }
}
