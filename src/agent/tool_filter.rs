//! Tool spec filtering for MCP and capability-based access control.
//!
//! Extracted from `loop_.rs` to isolate tool filtering logic.

use crate::config::schema::ToolFilterGroup;
use crate::tools::{Tool, ToolSpec};
use std::collections::HashSet;

pub(crate) fn glob_match(pattern: &str, name: &str) -> bool {
    match pattern.find('*') {
        None => pattern == name,
        Some(star) => {
            let prefix = &pattern[..star];
            let suffix = &pattern[star + 1..];
            name.starts_with(prefix)
                && name.ends_with(suffix)
                && name.len() >= prefix.len() + suffix.len()
        }
    }
}

/// Returns the subset of `tool_specs` that should be sent to the LLM for this turn.
///
/// Rules (mirrors NullClaw `filterToolSpecsForTurn`):
/// - Built-in tools (names that do not start with `"mcp_"`) always pass through.
/// - When `groups` is empty, all tools pass through (backward compatible default).
/// - An MCP tool is included if at least one group matches it:
///   - `always` group: included unconditionally if any pattern matches the tool name.
///   - `dynamic` group: included if any pattern matches AND the user message contains
///     at least one keyword (case-insensitive substring).
pub(crate) fn filter_tool_specs_for_turn(
    tool_specs: Vec<ToolSpec>,
    groups: &[ToolFilterGroup],
    user_message: &str,
) -> Vec<ToolSpec> {
    use crate::config::schema::ToolFilterGroupMode;

    if groups.is_empty() {
        return tool_specs;
    }

    let msg_lower = user_message.to_ascii_lowercase();

    tool_specs
        .into_iter()
        .filter(|spec| {
            // Built-in tools always pass through.
            if !spec.name.starts_with("mcp_") {
                return true;
            }
            // MCP tool: include if any active group matches.
            groups.iter().any(|group| {
                let pattern_matches = group.tools.iter().any(|pat| glob_match(pat, &spec.name));
                if !pattern_matches {
                    return false;
                }
                match group.mode {
                    ToolFilterGroupMode::Always => true,
                    ToolFilterGroupMode::Dynamic => group
                        .keywords
                        .iter()
                        .any(|kw| msg_lower.contains(&kw.to_ascii_lowercase())),
                }
            })
        })
        .collect()
}

/// Filters a tool spec list by an optional capability allowlist.
///
/// When `allowed` is `None`, all specs pass through unchanged.
/// When `allowed` is `Some(list)`, only specs whose name appears in the list
/// are retained. Unknown names in the allowlist are silently ignored.
pub(crate) fn filter_by_allowed_tools(
    specs: Vec<ToolSpec>,
    allowed: Option<&[String]>,
) -> Vec<ToolSpec> {
    match allowed {
        None => specs,
        Some(list) => specs
            .into_iter()
            .filter(|spec| list.iter().any(|name| name == &spec.name))
            .collect(),
    }
}

/// Computes the list of MCP tool names that should be excluded for a given turn
/// based on `tool_filter_groups` and the user message.
///
/// Returns an empty `Vec` when `groups` is empty (no filtering).
pub(crate) fn compute_excluded_mcp_tools(
    tools_registry: &[Box<dyn Tool>],
    groups: &[ToolFilterGroup],
    user_message: &str,
) -> Vec<String> {
    if groups.is_empty() {
        return Vec::new();
    }
    let filtered_specs = filter_tool_specs_for_turn(
        tools_registry.iter().map(|t| t.spec()).collect(),
        groups,
        user_message,
    );
    let included: HashSet<&str> = filtered_specs.iter().map(|s| s.name.as_str()).collect();
    tools_registry
        .iter()
        .filter(|t| t.name().starts_with("mcp_") && !included.contains(t.name()))
        .map(|t| t.name().to_string())
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_spec(name: &str) -> ToolSpec {
        ToolSpec {
            name: name.to_string(),
            description: String::new(),
            parameters: serde_json::json!({}),
        }
    }

    #[test]
    fn glob_match_exact() {
        assert!(glob_match("shell", "shell"));
        assert!(!glob_match("shell", "file_read"));
    }

    #[test]
    fn glob_match_wildcard() {
        assert!(glob_match("mcp_*", "mcp_github"));
        assert!(glob_match("mcp_git*", "mcp_github"));
        assert!(!glob_match("mcp_*", "shell"));
    }

    #[test]
    fn glob_match_suffix_wildcard() {
        assert!(glob_match("*_read", "file_read"));
        assert!(glob_match("*_read", "memory_read"));
        assert!(!glob_match("*_read", "file_write"));
    }

    #[test]
    fn filter_empty_groups_passes_all() {
        let specs = vec![make_spec("shell"), make_spec("mcp_github")];
        let result = filter_tool_specs_for_turn(specs, &[], "hello");
        assert_eq!(result.len(), 2);
    }

    #[test]
    fn filter_builtin_tools_always_pass() {
        let groups = vec![ToolFilterGroup {
            tools: vec!["mcp_special".to_string()],
            mode: crate::config::schema::ToolFilterGroupMode::Always,
            keywords: vec![],
        }];
        let specs = vec![
            make_spec("shell"),
            make_spec("file_read"),
            make_spec("mcp_other"),
        ];
        let result = filter_tool_specs_for_turn(specs, &groups, "hello");
        // shell and file_read pass (built-in), mcp_other is excluded
        assert_eq!(result.len(), 2);
        assert!(result.iter().any(|s| s.name == "shell"));
        assert!(result.iter().any(|s| s.name == "file_read"));
    }

    #[test]
    fn filter_by_allowed_tools_none_passes_all() {
        let specs = vec![make_spec("shell"), make_spec("file_read")];
        let result = filter_by_allowed_tools(specs, None);
        assert_eq!(result.len(), 2);
    }

    #[test]
    fn filter_by_allowed_tools_restricts_to_allowlist() {
        let specs = vec![
            make_spec("shell"),
            make_spec("file_read"),
            make_spec("memory_recall"),
        ];
        let allowed = vec!["shell".to_string(), "file_read".to_string()];
        let result = filter_by_allowed_tools(specs, Some(&allowed));
        assert_eq!(result.len(), 2);
        assert!(result.iter().all(|s| s.name != "memory_recall"));
    }
}
