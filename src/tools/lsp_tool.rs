use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use super::traits::{Tool, ToolResult};
use crate::security::SecurityPolicy;
use crate::tools::lsp_client::{DocumentSymbolEntry, LspManager, LspServerConfig, SymbolLocation};
use async_trait::async_trait;
use lsp_types::{Position, SymbolKind};
use serde_json::json;
use tokio::sync::Mutex;

pub struct LspTool {
    security: Arc<SecurityPolicy>,
    workspace_dir: PathBuf,
    server_configs: Vec<LspServerConfig>,
    manager: Mutex<Option<Arc<LspManager>>>,
}

impl LspTool {
    pub fn new(security: Arc<SecurityPolicy>, workspace_dir: PathBuf) -> Self {
        let server_configs = default_server_configs(&workspace_dir);
        Self::with_server_configs(security, workspace_dir, server_configs)
    }

    pub fn with_server_configs(
        security: Arc<SecurityPolicy>,
        workspace_dir: PathBuf,
        server_configs: Vec<LspServerConfig>,
    ) -> Self {
        Self {
            security,
            workspace_dir,
            server_configs,
            manager: Mutex::new(None),
        }
    }

    pub async fn shutdown(&self) -> anyhow::Result<()> {
        let manager = {
            let guard = self.manager.lock().await;
            guard.clone()
        };
        if let Some(manager) = manager {
            manager.shutdown().await?;
        }
        Ok(())
    }

    async fn manager(&self) -> anyhow::Result<Arc<LspManager>> {
        let mut guard = self.manager.lock().await;
        if let Some(manager) = guard.as_ref() {
            return Ok(manager.clone());
        }

        let manager = Arc::new(LspManager::new(self.server_configs.clone())?);
        *guard = Some(manager.clone());
        Ok(manager)
    }

    async fn resolve_path(&self, path: &str) -> anyhow::Result<PathBuf> {
        if !self.security.is_path_allowed(path) {
            anyhow::bail!("Path not allowed by security policy: {path}");
        }

        if !self.security.record_action() {
            anyhow::bail!("Rate limit exceeded: action budget exhausted");
        }

        let full_path = self.security.resolve_tool_path(path);
        let resolved_path = tokio::fs::canonicalize(&full_path)
            .await
            .map_err(|error| anyhow::anyhow!("Failed to resolve file path: {error}"))?;

        if !self.security.is_resolved_path_allowed(&resolved_path) {
            anyhow::bail!(
                "{}",
                self.security
                    .resolved_path_violation_message(&resolved_path)
            );
        }

        Ok(resolved_path)
    }

    fn position_from_args(args: &serde_json::Value) -> anyhow::Result<Position> {
        let line = args
            .get("line")
            .and_then(serde_json::Value::as_u64)
            .ok_or_else(|| anyhow::anyhow!("Missing 'line' parameter"))?;
        let character = args
            .get("character")
            .and_then(serde_json::Value::as_u64)
            .ok_or_else(|| anyhow::anyhow!("Missing 'character' parameter"))?;

        Ok(Position::new(
            u32::try_from(line).map_err(|_| anyhow::anyhow!("line is out of range"))?,
            u32::try_from(character).map_err(|_| anyhow::anyhow!("character is out of range"))?,
        ))
    }
}

#[async_trait]
impl Tool for LspTool {
    fn name(&self) -> &str {
        "lsp"
    }

    fn description(&self) -> &str {
        "Query a language server for document symbols, definitions, and references. Uses hardcoded first-cut defaults: .rs -> rust-analyzer, .py -> pyright-langserver --stdio."
    }

    fn parameters_schema(&self) -> serde_json::Value {
        json!({
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["document_symbols", "go_to_definition", "find_references"],
                    "description": "LSP operation to perform."
                },
                "file_path": {
                    "type": "string",
                    "description": "Path to the source file. Relative paths resolve from the current workspace."
                },
                "line": {
                    "type": "integer",
                    "description": "Zero-based line for go_to_definition and find_references."
                },
                "character": {
                    "type": "integer",
                    "description": "Zero-based character offset for go_to_definition and find_references."
                }
            },
            "required": ["action", "file_path"]
        })
    }

    async fn execute(&self, args: serde_json::Value) -> anyhow::Result<ToolResult> {
        let action = args
            .get("action")
            .and_then(serde_json::Value::as_str)
            .ok_or_else(|| anyhow::anyhow!("Missing 'action' parameter"))?;
        let file_path = args
            .get("file_path")
            .and_then(serde_json::Value::as_str)
            .ok_or_else(|| anyhow::anyhow!("Missing 'file_path' parameter"))?;

        let resolved_path = self.resolve_path(file_path).await?;
        let manager = self.manager().await?;
        let server = manager.server_name_for_path(&resolved_path)?;

        let results = match action {
            "document_symbols" => json!(format_symbols(
                manager.document_symbols(&resolved_path).await?
            )),
            "go_to_definition" => {
                let position = Self::position_from_args(&args)?;
                json!(format_locations(
                    manager.go_to_definition(&resolved_path, position).await?
                ))
            }
            "find_references" => {
                let position = Self::position_from_args(&args)?;
                json!(format_locations(
                    manager
                        .find_references(&resolved_path, position, false)
                        .await?
                ))
            }
            _ => anyhow::bail!("Unsupported action: {action}"),
        };

        Ok(ToolResult {
            success: true,
            output: serde_json::to_string_pretty(&json!({
                "action": action,
                "server": server,
                "workspace_root": self.workspace_dir.display().to_string(),
                "resolved_path": resolved_path.display().to_string(),
                "results": results,
            }))?,
            error: None,
        })
    }
}

fn default_server_configs(workspace_dir: &Path) -> Vec<LspServerConfig> {
    vec![
        LspServerConfig {
            name: "rust-analyzer".to_string(),
            command: "rust-analyzer".to_string(),
            args: Vec::new(),
            env: BTreeMap::new(),
            workspace_root: workspace_dir.to_path_buf(),
            initialization_options: None,
            extension_to_language: BTreeMap::from([(".rs".to_string(), "rust".to_string())]),
        },
        LspServerConfig {
            name: "pyright".to_string(),
            command: "pyright-langserver".to_string(),
            args: vec!["--stdio".to_string()],
            env: BTreeMap::new(),
            workspace_root: workspace_dir.to_path_buf(),
            initialization_options: None,
            extension_to_language: BTreeMap::from([(".py".to_string(), "python".to_string())]),
        },
    ]
}

fn format_locations(locations: Vec<SymbolLocation>) -> Vec<serde_json::Value> {
    locations
        .into_iter()
        .map(|location| {
            json!({
                "path": location.path.display().to_string(),
                "start": {
                    "line": location.range.start.line + 1,
                    "character": location.range.start.character + 1,
                },
                "end": {
                    "line": location.range.end.line + 1,
                    "character": location.range.end.character + 1,
                }
            })
        })
        .collect()
}

fn format_symbols(symbols: Vec<DocumentSymbolEntry>) -> Vec<serde_json::Value> {
    symbols.into_iter().map(format_symbol).collect()
}

fn format_symbol(symbol: DocumentSymbolEntry) -> serde_json::Value {
    json!({
        "name": symbol.name,
        "detail": symbol.detail,
        "kind": symbol_kind_name(symbol.kind),
        "path": symbol.path.display().to_string(),
        "container_name": symbol.container_name,
        "start": {
            "line": symbol.range.start.line + 1,
            "character": symbol.range.start.character + 1,
        },
        "end": {
            "line": symbol.range.end.line + 1,
            "character": symbol.range.end.character + 1,
        },
        "selection_start": {
            "line": symbol.selection_range.start.line + 1,
            "character": symbol.selection_range.start.character + 1,
        },
        "selection_end": {
            "line": symbol.selection_range.end.line + 1,
            "character": symbol.selection_range.end.character + 1,
        },
        "children": symbol.children.into_iter().map(format_symbol).collect::<Vec<_>>(),
    })
}

fn symbol_kind_name(kind: SymbolKind) -> &'static str {
    match kind {
        SymbolKind::FILE => "file",
        SymbolKind::MODULE => "module",
        SymbolKind::NAMESPACE => "namespace",
        SymbolKind::PACKAGE => "package",
        SymbolKind::CLASS => "class",
        SymbolKind::METHOD => "method",
        SymbolKind::PROPERTY => "property",
        SymbolKind::FIELD => "field",
        SymbolKind::CONSTRUCTOR => "constructor",
        SymbolKind::ENUM => "enum",
        SymbolKind::INTERFACE => "interface",
        SymbolKind::FUNCTION => "function",
        SymbolKind::VARIABLE => "variable",
        SymbolKind::CONSTANT => "constant",
        SymbolKind::STRING => "string",
        SymbolKind::NUMBER => "number",
        SymbolKind::BOOLEAN => "boolean",
        SymbolKind::ARRAY => "array",
        SymbolKind::OBJECT => "object",
        SymbolKind::KEY => "key",
        SymbolKind::NULL => "null",
        SymbolKind::ENUM_MEMBER => "enum_member",
        SymbolKind::STRUCT => "struct",
        SymbolKind::EVENT => "event",
        SymbolKind::OPERATOR => "operator",
        SymbolKind::TYPE_PARAMETER => "type_parameter",
        _ => "unknown",
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;
    use std::fs;
    use std::path::PathBuf;
    use std::process::Command;
    use std::sync::Arc;
    use std::time::{SystemTime, UNIX_EPOCH};

    use serde_json::json;

    use crate::security::SecurityPolicy;
    use crate::tools::Tool;
    use crate::tools::lsp_client::LspServerConfig;

    use super::LspTool;

    fn temp_dir(label: &str) -> PathBuf {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("time should be after epoch")
            .as_nanos();
        std::env::temp_dir().join(format!("rain-lsp-tool-{label}-{nanos}"))
    }

    fn python_command() -> Option<String> {
        ["python", "python3"].into_iter().find_map(|candidate| {
            Command::new(candidate)
                .arg("--version")
                .output()
                .ok()
                .filter(|output| output.status.success())
                .map(|_| candidate.to_string())
        })
    }

    fn write_mock_server_script(root: &std::path::Path) -> PathBuf {
        let script_path = root.join("mock_lsp_server.py");
        fs::write(
            &script_path,
            r#"import json
import sys


def read_message():
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line == b"\r\n":
            break
        key, value = line.decode("utf-8").split(":", 1)
        headers[key.lower()] = value.strip()
    length = int(headers["content-length"])
    body = sys.stdin.buffer.read(length)
    return json.loads(body)


def write_message(payload):
    raw = json.dumps(payload).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(raw)}\r\n\r\n".encode("utf-8"))
    sys.stdout.buffer.write(raw)
    sys.stdout.buffer.flush()


while True:
    message = read_message()
    if message is None:
        break

    method = message.get("method")
    if method == "initialize":
        write_message({
            "jsonrpc": "2.0",
            "id": message["id"],
            "result": {
                "capabilities": {
                    "definitionProvider": True,
                    "referencesProvider": True,
                    "documentSymbolProvider": True,
                    "textDocumentSync": 1,
                }
            },
        })
    elif method == "initialized":
        continue
    elif method == "textDocument/didOpen":
        continue
    elif method == "textDocument/documentSymbol":
        uri = message["params"]["textDocument"]["uri"]
        write_message({
            "jsonrpc": "2.0",
            "id": message["id"],
            "result": [
                {
                    "name": "main",
                    "kind": 12,
                    "location": {
                        "uri": uri,
                        "range": {
                            "start": {"line": 0, "character": 0},
                            "end": {"line": 0, "character": 11},
                        }
                    }
                }
            ],
        })
    elif method == "textDocument/definition":
        uri = message["params"]["textDocument"]["uri"]
        write_message({
            "jsonrpc": "2.0",
            "id": message["id"],
            "result": [
                {
                    "uri": uri,
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 4},
                    },
                }
            ],
        })
    elif method == "textDocument/references":
        uri = message["params"]["textDocument"]["uri"]
        write_message({
            "jsonrpc": "2.0",
            "id": message["id"],
            "result": [
                {
                    "uri": uri,
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 4},
                    },
                }
            ],
        })
    elif method == "shutdown":
        write_message({"jsonrpc": "2.0", "id": message["id"], "result": None})
    elif method == "exit":
        break
"#,
        )
        .expect("mock server should be written");
        script_path
    }

    #[tokio::test(flavor = "current_thread")]
    async fn execute_returns_absolute_path_and_symbol_data() {
        let Some(python) = python_command() else {
            return;
        };

        let root = temp_dir("tool");
        fs::create_dir_all(root.join("src")).expect("workspace root should exist");
        let script_path = write_mock_server_script(&root);
        let source_path = root.join("src").join("main.rs");
        fs::write(&source_path, "fn main() {}\n").expect("source file should exist");

        let tool = LspTool::with_server_configs(
            Arc::new(SecurityPolicy {
                workspace_dir: root.clone(),
                ..SecurityPolicy::default()
            }),
            root.clone(),
            vec![LspServerConfig {
                name: "rust-analyzer".to_string(),
                command: python,
                args: vec![script_path.display().to_string()],
                env: BTreeMap::new(),
                workspace_root: root.clone(),
                initialization_options: None,
                extension_to_language: BTreeMap::from([(".rs".to_string(), "rust".to_string())]),
            }],
        );

        let result = tool
            .execute(json!({
                "action": "document_symbols",
                "file_path": "src/main.rs"
            }))
            .await
            .expect("tool execution should succeed");

        assert!(result.success);
        let payload: serde_json::Value =
            serde_json::from_str(&result.output).expect("tool output should be valid json");
        assert_eq!(payload["action"], "document_symbols");
        assert_eq!(
            payload["resolved_path"],
            source_path.canonicalize().unwrap().display().to_string()
        );
        assert_eq!(payload["results"][0]["name"], "main");

        tool.shutdown().await.expect("tool shutdown should succeed");
        fs::remove_dir_all(root).expect("temp workspace should be removed");
    }
}
