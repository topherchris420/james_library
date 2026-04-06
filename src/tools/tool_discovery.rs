use super::toolbox_manager::{ToolActivationStatus, ToolboxManager};
use super::traits::{Tool, ToolResult};
use async_trait::async_trait;
use serde_json::json;

const DEFAULT_MAX_RESULTS: usize = 10;

pub struct ToolDiscoveryTool {
    toolbox: ToolboxManager,
}

impl ToolDiscoveryTool {
    pub fn new(toolbox: ToolboxManager) -> Self {
        Self { toolbox }
    }
}

#[async_trait]
impl Tool for ToolDiscoveryTool {
    fn name(&self) -> &str {
        "tool_discovery"
    }

    fn description(&self) -> &str {
        "Discover inactive tools by category or keyword, then activate a specific tool for the current session."
    }

    fn parameters_schema(&self) -> serde_json::Value {
        json!({
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list_categories", "query", "activate", "status"],
                    "description": "Toolbox action to perform."
                },
                "category": {
                    "type": "string",
                    "description": "Optional category filter such as hardware, web, or physics."
                },
                "query": {
                    "type": "string",
                    "description": "Optional keyword search across tool names, descriptions, and categories."
                },
                "tool_name": {
                    "type": "string",
                    "description": "Exact tool name to activate."
                },
                "max_results": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": DEFAULT_MAX_RESULTS,
                    "description": "Maximum number of query matches to return."
                }
            },
            "required": ["action"]
        })
    }

    async fn execute(&self, args: serde_json::Value) -> anyhow::Result<ToolResult> {
        let action = args
            .get("action")
            .and_then(|value| value.as_str())
            .unwrap_or_default();

        match action {
            "list_categories" => Ok(ToolResult {
                success: true,
                output: serde_json::to_string_pretty(&json!({
                    "categories": self.toolbox.category_counts(),
                }))?,
                error: None,
            }),
            "query" => {
                let category = args.get("category").and_then(|value| value.as_str());
                let query = args.get("query").and_then(|value| value.as_str());
                let max_results = args
                    .get("max_results")
                    .and_then(|value| value.as_u64())
                    .map(|value| value.clamp(1, 50) as usize)
                    .unwrap_or(DEFAULT_MAX_RESULTS);

                let matches = self.toolbox.query(category, query, max_results);
                Ok(ToolResult {
                    success: true,
                    output: serde_json::to_string_pretty(&json!({
                        "matches": matches,
                    }))?,
                    error: None,
                })
            }
            "activate" => {
                let Some(tool_name) = args.get("tool_name").and_then(|value| value.as_str()) else {
                    return Ok(ToolResult {
                        success: false,
                        output: String::new(),
                        error: Some("tool_name is required for action=activate".into()),
                    });
                };

                match self.toolbox.activate_tool(tool_name) {
                    Ok(result) => Ok(ToolResult {
                        success: true,
                        output: serde_json::to_string_pretty(&json!({
                            "status": match result.status {
                                ToolActivationStatus::Activated => "activated",
                                ToolActivationStatus::AlreadyActive => "already_active",
                            },
                            "tool": result.tool,
                            "message": "The active toolset will refresh on the next model turn.",
                        }))?,
                        error: None,
                    }),
                    Err(err) => Ok(ToolResult {
                        success: false,
                        output: String::new(),
                        error: Some(err.to_string()),
                    }),
                }
            }
            "status" => Ok(ToolResult {
                success: true,
                output: serde_json::to_string_pretty(&json!({
                    "active_tools": self.toolbox.active_tool_names(),
                    "discoverable_categories": self.toolbox.category_counts(),
                }))?,
                error: None,
            }),
            _ => Ok(ToolResult {
                success: false,
                output: String::new(),
                error: Some(format!("unknown action: {action}")),
            }),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::tools::toolbox_manager::ToolboxAccessConfig;
    use async_trait::async_trait;
    use std::sync::Arc;

    struct DummyTool {
        name: &'static str,
    }

    #[async_trait]
    impl Tool for DummyTool {
        fn name(&self) -> &str {
            self.name
        }

        fn description(&self) -> &str {
            "Dummy tool"
        }

        fn parameters_schema(&self) -> serde_json::Value {
            json!({
                "type": "object",
                "properties": {}
            })
        }

        async fn execute(&self, _args: serde_json::Value) -> anyhow::Result<ToolResult> {
            Ok(ToolResult {
                success: true,
                output: self.name.to_string(),
                error: None,
            })
        }
    }

    #[tokio::test]
    async fn activate_action_turns_on_requested_tool() {
        let toolbox = ToolboxManager::from_registry(
            vec![Arc::new(DummyTool { name: "web_fetch" })],
            ToolboxAccessConfig {
                discoverable_tools: vec!["web_fetch".into()],
                ..ToolboxAccessConfig::default()
            },
        );
        let tool = ToolDiscoveryTool::new(toolbox.clone());

        let result = tool
            .execute(json!({
                "action": "activate",
                "tool_name": "web_fetch"
            }))
            .await
            .unwrap();

        assert!(result.success);
        assert!(
            toolbox
                .active_tool_names()
                .contains(&"web_fetch".to_string())
        );
    }

    #[tokio::test]
    async fn query_action_returns_matching_tools() {
        let toolbox = ToolboxManager::from_registry(
            vec![Arc::new(DummyTool {
                name: "hardware_board_info",
            })],
            ToolboxAccessConfig {
                discoverable_tools: vec!["hardware_board_info".into()],
                ..ToolboxAccessConfig::default()
            },
        );
        let tool = ToolDiscoveryTool::new(toolbox);

        let result = tool
            .execute(json!({
                "action": "query",
                "category": "hardware"
            }))
            .await
            .unwrap();

        assert!(result.success);
        assert!(result.output.contains("hardware_board_info"));
    }
}
