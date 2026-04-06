//! TRIBE v2 brain-encoding tool — predicts fMRI brain responses from multimedia.
//!
//! Delegates to a TRIBE v2 Python sidecar HTTP service (see `tools/tribev2_sidecar/`).
//! The sidecar wraps Facebook Research's TRIBE v2 model, which predicts cortical
//! activation on the fsaverage5 mesh (~20k vertices) from video, audio, or text.
//!
//! **License**: TRIBE v2 is CC-BY-NC 4.0 (non-commercial use only).

use super::traits::{Tool, ToolResult};
use crate::security::SecurityPolicy;
use crate::security::policy::ToolOperation;
use async_trait::async_trait;
use serde::Deserialize;
use serde_json::{Value, json};
use std::fmt::Write;
use std::sync::Arc;
use std::time::Duration;

const CONNECT_TIMEOUT_SECS: u64 = 10;

// ── Sidecar response types ──────────────────────────────────────────────────

#[derive(Debug, Deserialize)]
struct PredictResponse {
    /// Shape description, e.g. "(N, 20484)"
    shape: String,
    /// Number of time segments
    num_segments: usize,
    /// Per-segment summary statistics
    segments: Vec<SegmentSummary>,
}

#[derive(Debug, Deserialize)]
struct SegmentSummary {
    index: usize,
    mean_activation: f64,
    max_activation: f64,
    min_activation: f64,
}

#[derive(Debug, Deserialize)]
struct HealthResponse {
    status: String,
    model_loaded: bool,
}

// ── Tool struct ─────────────────────────────────────────────────────────────

/// Predicts fMRI brain responses from multimedia via a TRIBE v2 sidecar service.
pub struct TribeV2Tool {
    security: Arc<SecurityPolicy>,
    endpoint: String,
    timeout_secs: u64,
}

impl TribeV2Tool {
    pub fn new(endpoint: String, timeout_secs: u64, security: Arc<SecurityPolicy>) -> Self {
        Self {
            security,
            endpoint: endpoint.trim_end_matches('/').to_string(),
            timeout_secs,
        }
    }

    fn build_client(&self) -> anyhow::Result<reqwest::Client> {
        let builder = reqwest::Client::builder()
            .timeout(Duration::from_secs(self.timeout_secs))
            .connect_timeout(Duration::from_secs(CONNECT_TIMEOUT_SECS))
            .user_agent("R.A.I.N.-tribev2/1.0");

        let builder = crate::config::apply_runtime_proxy_to_builder(builder, "tool.tribev2");
        Ok(builder.build()?)
    }

    async fn predict(&self, input_type: &str, input_value: &str) -> anyhow::Result<String> {
        let client = self.build_client()?;
        let url = format!("{}/predict", self.endpoint);

        let body = json!({
            "input_type": input_type,
            "input_value": input_value,
        });

        let response = client.post(&url).json(&body).send().await.map_err(|e| {
            anyhow::anyhow!(
                "Failed to connect to TRIBE v2 sidecar at {}: {}. \
                     Ensure the sidecar is running (see tools/tribev2_sidecar/README.md).",
                self.endpoint,
                e
            )
        })?;

        let status = response.status();
        if !status.is_success() {
            let error_body = response.text().await.unwrap_or_default();
            anyhow::bail!("TRIBE v2 sidecar returned HTTP {status}: {error_body}");
        }

        let result: PredictResponse = response
            .json()
            .await
            .map_err(|e| anyhow::anyhow!("Failed to parse TRIBE v2 response: {e}"))?;

        Ok(Self::format_output(&result, input_type, input_value))
    }

    async fn health(&self) -> anyhow::Result<String> {
        let client = self.build_client()?;
        let url = format!("{}/health", self.endpoint);

        let response = client.get(&url).send().await.map_err(|e| {
            anyhow::anyhow!(
                "Failed to connect to TRIBE v2 sidecar at {}: {}",
                self.endpoint,
                e
            )
        })?;

        let status = response.status();
        if !status.is_success() {
            let error_body = response.text().await.unwrap_or_default();
            anyhow::bail!("TRIBE v2 sidecar health check returned HTTP {status}: {error_body}");
        }

        let result: HealthResponse = response.json().await?;
        Ok(format!(
            "TRIBE v2 sidecar status: {} | Model loaded: {}",
            result.status, result.model_loaded
        ))
    }

    fn format_output(result: &PredictResponse, input_type: &str, input_value: &str) -> String {
        let mut out = String::new();
        let _ = write!(
            out,
            "TRIBE v2 Brain Prediction\n\
             ─────────────────────────\n\
             Input type : {input_type}\n\
             Input      : {input_value}\n\
             Prediction shape: {} ({} segments x fsaverage5 vertices)\n",
            result.shape, result.num_segments,
        );

        if !result.segments.is_empty() {
            out.push_str("\nSegment Summaries\n─────────────────\n");
            for seg in &result.segments {
                let _ = writeln!(
                    out,
                    "  Segment {:3}: mean={:.4}  max={:.4}  min={:.4}",
                    seg.index, seg.mean_activation, seg.max_activation, seg.min_activation,
                );
            }
        }

        out
    }
}

// ── Tool trait ──────────────────────────────────────────────────────────────

#[async_trait]
impl Tool for TribeV2Tool {
    fn name(&self) -> &str {
        "tribev2_predict"
    }

    fn description(&self) -> &str {
        "Predict fMRI brain responses from multimedia inputs using Facebook Research's \
         TRIBE v2 model. Accepts video file paths, audio file paths, or raw text. \
         Returns predicted cortical activation on the fsaverage5 mesh (~20k vertices). \
         Requires a running TRIBE v2 sidecar service."
    }

    fn parameters_schema(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["predict", "health"],
                    "description": "Action to perform. 'predict' runs brain encoding on input. \
                                    'health' checks sidecar status. Default: 'predict'."
                },
                "input_type": {
                    "type": "string",
                    "enum": ["video", "audio", "text"],
                    "description": "Type of input stimulus. Required for 'predict' action."
                },
                "input_value": {
                    "type": "string",
                    "description": "For 'video'/'audio': absolute file path accessible to the \
                                    sidecar. For 'text': the raw text string. Required for \
                                    'predict' action."
                }
            },
            "required": []
        })
    }

    async fn execute(&self, args: Value) -> anyhow::Result<ToolResult> {
        let action = args
            .get("action")
            .and_then(|v| v.as_str())
            .unwrap_or("predict");

        let operation = match action {
            "health" => ToolOperation::Read,
            _ => ToolOperation::Act,
        };
        if let Err(error) = self
            .security
            .enforce_tool_operation(operation, "tribev2_predict")
        {
            return Ok(ToolResult {
                success: false,
                output: String::new(),
                error: Some(error.to_string()),
            });
        }

        match action {
            "health" => match self.health().await {
                Ok(output) => Ok(ToolResult {
                    success: true,
                    output,
                    error: None,
                }),
                Err(e) => Ok(ToolResult {
                    success: false,
                    output: String::new(),
                    error: Some(e.to_string()),
                }),
            },
            "predict" => {
                let input_type = match args.get("input_type").and_then(|v| v.as_str()) {
                    Some(t) if matches!(t, "video" | "audio" | "text") => t,
                    Some(t) => {
                        return Ok(ToolResult {
                            success: false,
                            output: String::new(),
                            error: Some(format!(
                                "Invalid input_type '{t}'. Must be 'video', 'audio', or 'text'."
                            )),
                        });
                    }
                    None => {
                        return Ok(ToolResult {
                            success: false,
                            output: String::new(),
                            error: Some(
                                "Missing required parameter 'input_type' for predict action."
                                    .into(),
                            ),
                        });
                    }
                };

                let input_value = match args.get("input_value").and_then(|v| v.as_str()) {
                    Some(v) if !v.trim().is_empty() => v.trim(),
                    _ => {
                        return Ok(ToolResult {
                            success: false,
                            output: String::new(),
                            error: Some(
                                "Missing required parameter 'input_value' for predict action."
                                    .into(),
                            ),
                        });
                    }
                };

                match self.predict(input_type, input_value).await {
                    Ok(output) => Ok(ToolResult {
                        success: true,
                        output,
                        error: None,
                    }),
                    Err(e) => Ok(ToolResult {
                        success: false,
                        output: String::new(),
                        error: Some(e.to_string()),
                    }),
                }
            }
            other => Ok(ToolResult {
                success: false,
                output: String::new(),
                error: Some(format!(
                    "Unknown action '{other}'. Must be 'predict' or 'health'."
                )),
            }),
        }
    }
}

// ── Tests ───────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn make_tool() -> TribeV2Tool {
        TribeV2Tool::new(
            "http://127.0.0.1:8100".into(),
            120,
            Arc::new(SecurityPolicy::default()),
        )
    }

    #[test]
    fn name_is_tribev2_predict() {
        assert_eq!(make_tool().name(), "tribev2_predict");
    }

    #[test]
    fn description_is_non_empty() {
        assert!(!make_tool().description().is_empty());
    }

    #[test]
    fn parameters_schema_is_valid_object() {
        let schema = make_tool().parameters_schema();
        assert_eq!(schema["type"], "object");
        assert!(schema["properties"].is_object());
    }

    #[test]
    fn schema_has_action_property() {
        let schema = make_tool().parameters_schema();
        let action = &schema["properties"]["action"];
        assert!(action.is_object());
        let enums = action["enum"].as_array().unwrap();
        assert!(enums.contains(&Value::String("predict".into())));
        assert!(enums.contains(&Value::String("health".into())));
    }

    #[test]
    fn schema_has_input_type_property() {
        let schema = make_tool().parameters_schema();
        let input_type = &schema["properties"]["input_type"];
        let enums = input_type["enum"].as_array().unwrap();
        assert!(enums.contains(&Value::String("video".into())));
        assert!(enums.contains(&Value::String("audio".into())));
        assert!(enums.contains(&Value::String("text".into())));
    }

    #[test]
    fn schema_has_input_value_property() {
        let schema = make_tool().parameters_schema();
        assert!(schema["properties"]["input_value"].is_object());
    }

    #[test]
    fn endpoint_trailing_slash_stripped() {
        let tool = TribeV2Tool::new(
            "http://localhost:8100/".into(),
            60,
            Arc::new(SecurityPolicy::default()),
        );
        assert_eq!(tool.endpoint, "http://localhost:8100");
    }

    #[test]
    fn spec_reflects_tool_metadata() {
        let tool = make_tool();
        let spec = tool.spec();
        assert_eq!(spec.name, "tribev2_predict");
        assert_eq!(spec.description, tool.description());
        assert!(spec.parameters.is_object());
    }

    #[test]
    fn format_output_contains_expected_fields() {
        let result = PredictResponse {
            shape: "(10, 20484)".into(),
            num_segments: 10,
            segments: vec![
                SegmentSummary {
                    index: 0,
                    mean_activation: 0.1234,
                    max_activation: 0.9876,
                    min_activation: -0.5432,
                },
                SegmentSummary {
                    index: 1,
                    mean_activation: 0.2345,
                    max_activation: 0.8765,
                    min_activation: -0.4321,
                },
            ],
        };

        let out = TribeV2Tool::format_output(&result, "video", "/path/to/video.mp4");
        assert!(out.contains("TRIBE v2 Brain Prediction"));
        assert!(out.contains("video"));
        assert!(out.contains("/path/to/video.mp4"));
        assert!(out.contains("(10, 20484)"));
        assert!(out.contains("10 segments"));
        assert!(out.contains("Segment   0"));
        assert!(out.contains("0.1234"));
        assert!(out.contains("0.9876"));
    }

    #[test]
    fn format_output_empty_segments() {
        let result = PredictResponse {
            shape: "(0, 20484)".into(),
            num_segments: 0,
            segments: vec![],
        };

        let out = TribeV2Tool::format_output(&result, "text", "hello world");
        assert!(out.contains("TRIBE v2 Brain Prediction"));
        assert!(out.contains("text"));
        assert!(!out.contains("Segment Summaries"));
    }

    // ── execute: parameter validation (no network needed) ───────────────────

    #[tokio::test]
    async fn execute_missing_input_type_returns_error() {
        let result = make_tool()
            .execute(json!({"action": "predict", "input_value": "hello"}))
            .await
            .unwrap();
        assert!(!result.success);
        assert!(result.error.unwrap().contains("input_type"));
    }

    #[tokio::test]
    async fn execute_missing_input_value_returns_error() {
        let result = make_tool()
            .execute(json!({"action": "predict", "input_type": "text"}))
            .await
            .unwrap();
        assert!(!result.success);
        assert!(result.error.unwrap().contains("input_value"));
    }

    #[tokio::test]
    async fn execute_invalid_input_type_returns_error() {
        let result = make_tool()
            .execute(json!({"action": "predict", "input_type": "image", "input_value": "test"}))
            .await
            .unwrap();
        assert!(!result.success);
        assert!(result.error.unwrap().contains("Invalid input_type"));
    }

    #[tokio::test]
    async fn execute_empty_input_value_returns_error() {
        let result = make_tool()
            .execute(json!({"action": "predict", "input_type": "text", "input_value": "   "}))
            .await
            .unwrap();
        assert!(!result.success);
        assert!(result.error.unwrap().contains("input_value"));
    }

    #[tokio::test]
    async fn execute_unknown_action_returns_error() {
        let result = make_tool()
            .execute(json!({"action": "train"}))
            .await
            .unwrap();
        assert!(!result.success);
        assert!(result.error.unwrap().contains("Unknown action"));
    }
}
