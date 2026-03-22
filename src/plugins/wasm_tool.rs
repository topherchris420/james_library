//! Bridge between WASM plugins and the Tool trait.

use crate::tools::traits::{Tool, ToolResult};
use async_trait::async_trait;
use serde_json::Value;

/// A tool backed by a WASM plugin function.
pub struct WasmTool {
    name: String,
    description: String,
    plugin_name: String,
    function_name: String,
    parameters_schema: Value,
}

impl WasmTool {
    pub fn new(
        name: String,
        description: String,
        plugin_name: String,
        function_name: String,
        parameters_schema: Value,
    ) -> Self {
        Self {
            name,
            description,
            plugin_name,
            function_name,
            parameters_schema,
        }
    }
}

#[async_trait]
impl Tool for WasmTool {
    fn name(&self) -> &str {
        &self.name
    }

    fn description(&self) -> &str {
        &self.description
    }

    fn parameters_schema(&self) -> Value {
        self.parameters_schema.clone()
    }

    async fn execute(&self, _args: Value) -> anyhow::Result<ToolResult> {
        // Extism plugin runtime integration is pending; fail explicitly so callers
        // know the tool exists but cannot execute yet.
        Ok(ToolResult {
            success: false,
            output: String::new(),
            error: Some(format!(
                "WASM plugin {}/{} is registered but the Extism execution bridge is not yet wired",
                self.plugin_name, self.function_name,
            )),
        })
    }
}
