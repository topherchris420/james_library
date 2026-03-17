use crate::providers::ToolCall;
use regex::Regex;
use std::sync::LazyLock;

#[derive(Debug, Clone)]
pub(crate) struct ParsedToolCall {
    pub(crate) name: String,
    pub(crate) arguments: serde_json::Value,
    pub(crate) tool_call_id: Option<String>,
}

// ── Helper Functions ──────────────────────────────────────────────────────

pub(crate) fn parse_arguments_value(raw: Option<&serde_json::Value>) -> serde_json::Value {
    match raw {
        Some(serde_json::Value::String(s)) => serde_json::from_str::<serde_json::Value>(s)
            .unwrap_or_else(|_| serde_json::Value::Object(serde_json::Map::new())),
        Some(value) => value.clone(),
        None => serde_json::Value::Object(serde_json::Map::new()),
    }
}

fn parse_tool_call_id(
    root: &serde_json::Value,
    function: Option<&serde_json::Value>,
) -> Option<String> {
    function
        .and_then(|func| func.get("id"))
        .or_else(|| root.get("id"))
        .or_else(|| root.get("tool_call_id"))
        .or_else(|| root.get("call_id"))
        .and_then(serde_json::Value::as_str)
        .map(str::trim)
        .filter(|id| !id.is_empty())
        .map(ToString::to_string)
}

fn canonicalize_json_for_tool_signature(value: &serde_json::Value) -> serde_json::Value {
    match value {
        serde_json::Value::Object(map) => {
            let mut keys: Vec<String> = map.keys().cloned().collect();
            keys.sort_unstable();
            let mut ordered = serde_json::Map::new();
            for key in keys {
                if let Some(child) = map.get(&key) {
                    ordered.insert(key, canonicalize_json_for_tool_signature(child));
                }
            }
            serde_json::Value::Object(ordered)
        }
        serde_json::Value::Array(items) => serde_json::Value::Array(
            items
                .iter()
                .map(canonicalize_json_for_tool_signature)
                .collect(),
        ),
        _ => value.clone(),
    }
}

pub(crate) fn tool_call_signature(name: &str, arguments: &serde_json::Value) -> (String, String) {
    let canonical_args = canonicalize_json_for_tool_signature(arguments);
    let args_json = serde_json::to_string(&canonical_args).unwrap_or_else(|_| "{}".to_string());
    (name.trim().to_ascii_lowercase(), args_json)
}

pub(crate) fn parse_tool_call_value(value: &serde_json::Value) -> Option<ParsedToolCall> {
    if let Some(function) = value.get("function") {
        let tool_call_id = parse_tool_call_id(value, Some(function));
        let name = function
            .get("name")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_string();
        if !name.is_empty() {
            let arguments = parse_arguments_value(
                function
                    .get("arguments")
                    .or_else(|| function.get("parameters")),
            );
            return Some(ParsedToolCall {
                name,
                arguments,
                tool_call_id,
            });
        }
    }

    let tool_call_id = parse_tool_call_id(value, None);
    let name = value
        .get("name")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();

    if name.is_empty() {
        return None;
    }

    let arguments =
        parse_arguments_value(value.get("arguments").or_else(|| value.get("parameters")));
    Some(ParsedToolCall {
        name,
        arguments,
        tool_call_id,
    })
}

pub(crate) fn parse_tool_calls_from_json_value(value: &serde_json::Value) -> Vec<ParsedToolCall> {
    let mut calls = Vec::new();

    if let Some(tool_calls) = value.get("tool_calls").and_then(|v| v.as_array()) {
        for call in tool_calls {
            if let Some(parsed) = parse_tool_call_value(call) {
                calls.push(parsed);
            }
        }

        if !calls.is_empty() {
            return calls;
        }
    }

    if let Some(array) = value.as_array() {
        for item in array {
            if let Some(parsed) = parse_tool_call_value(item) {
                calls.push(parsed);
            }
        }
        return calls;
    }

    if let Some(parsed) = parse_tool_call_value(value) {
        calls.push(parsed);
    }

    calls
}

// ── XML Parsing ───────────────────────────────────────────────────────────

fn is_xml_meta_tag(tag: &str) -> bool {
    let normalized = tag.to_ascii_lowercase();
    matches!(
        normalized.as_str(),
        "tool_call"
            | "toolcall"
            | "tool-call"
            | "invoke"
            | "thinking"
            | "thought"
            | "analysis"
            | "reasoning"
            | "reflection"
    )
}

/// Match opening XML tags: `<tag_name>`.  Does NOT use backreferences.
static XML_OPEN_TAG_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"<([a-zA-Z_][a-zA-Z0-9_-]*)>").unwrap());

/// MiniMax XML invoke format:
/// `<invoke name="shell"><parameter name="command">pwd</parameter></invoke>`
static MINIMAX_INVOKE_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r#"(?is)<invoke\b[^>]*\bname\s*=\s*(?:"([^"]+)"|'([^']+)')[^>]*>(.*?)</invoke>"#)
        .unwrap()
});

static MINIMAX_PARAMETER_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
        r#"(?is)<parameter\b[^>]*\bname\s*=\s*(?:"([^"]+)"|'([^']+)')[^>]*>(.*?)</parameter>"#,
    )
    .unwrap()
});

/// Extracts all `<tag>…</tag>` pairs from `input`, returning `(tag_name, inner_content)`.
/// Handles matching closing tags without regex backreferences.
fn extract_xml_pairs(input: &str) -> Vec<(&str, &str)> {
    let mut results = Vec::new();
    let mut search_start = 0;
    while let Some(open_cap) = XML_OPEN_TAG_RE.captures(&input[search_start..]) {
        let full_open = open_cap.get(0).unwrap();
        let tag_name = open_cap.get(1).unwrap().as_str();
        let open_end = search_start + full_open.end();

        let closing_tag = format!("</{tag_name}>");
        if let Some(close_pos) = input[open_end..].find(&closing_tag) {
            let inner = &input[open_end..open_end + close_pos];
            results.push((tag_name, inner.trim()));
            search_start = open_end + close_pos + closing_tag.len();
        } else {
            search_start = open_end;
        }
    }
    results
}

/// Parse XML-style tool calls in `<tool_call>` bodies.
/// Supports both nested argument tags and JSON argument payloads:
/// - `<memory_recall><query>...</query></memory_recall>`
/// - `<shell>{"command":"pwd"}</shell>`
fn parse_xml_tool_calls(xml_content: &str) -> Option<Vec<ParsedToolCall>> {
    let mut calls = Vec::new();
    let trimmed = xml_content.trim();

    if !trimmed.starts_with('<') || !trimmed.contains('>') {
        return None;
    }

    for (tool_name_str, inner_content) in extract_xml_pairs(trimmed) {
        let tool_name = tool_name_str.to_string();
        if is_xml_meta_tag(&tool_name) {
            continue;
        }

        if inner_content.is_empty() {
            continue;
        }

        let mut args = serde_json::Map::new();

        if let Some(first_json) = extract_json_values(inner_content).into_iter().next() {
            match first_json {
                serde_json::Value::Object(object_args) => {
                    args = object_args;
                }
                other => {
                    args.insert("value".to_string(), other);
                }
            }
        } else {
            for (key_str, value) in extract_xml_pairs(inner_content) {
                let key = key_str.to_string();
                if is_xml_meta_tag(&key) {
                    continue;
                }
                if !value.is_empty() {
                    args.insert(key, serde_json::Value::String(value.to_string()));
                }
            }

            if args.is_empty() {
                args.insert(
                    "content".to_string(),
                    serde_json::Value::String(inner_content.to_string()),
                );
            }
        }

        calls.push(ParsedToolCall {
            name: tool_name,
            arguments: serde_json::Value::Object(args),
            tool_call_id: None,
        });
    }

    if calls.is_empty() {
        None
    } else {
        Some(calls)
    }
}

/// Parse MiniMax-style XML tool calls with attributed invoke/parameter tags.
fn parse_minimax_invoke_calls(response: &str) -> Option<(String, Vec<ParsedToolCall>)> {
    let mut calls = Vec::new();
    let mut text_parts = Vec::new();
    let mut last_end = 0usize;

    for cap in MINIMAX_INVOKE_RE.captures_iter(response) {
        let Some(full_match) = cap.get(0) else {
            continue;
        };

        let before = response[last_end..full_match.start()].trim();
        if !before.is_empty() {
            text_parts.push(before.to_string());
        }

        let name = cap
            .get(1)
            .or_else(|| cap.get(2))
            .map(|m| m.as_str().trim())
            .filter(|v| !v.is_empty());
        let body = cap.get(3).map(|m| m.as_str()).unwrap_or("").trim();
        last_end = full_match.end();

        let Some(name) = name else {
            continue;
        };

        let mut args = serde_json::Map::new();
        for param_cap in MINIMAX_PARAMETER_RE.captures_iter(body) {
            let key = param_cap
                .get(1)
                .or_else(|| param_cap.get(2))
                .map(|m| m.as_str().trim())
                .unwrap_or_default();
            if key.is_empty() {
                continue;
            }
            let value = param_cap
                .get(3)
                .map(|m| m.as_str().trim())
                .unwrap_or_default();
            if value.is_empty() {
                continue;
            }

            let parsed = extract_json_values(value).into_iter().next();
            args.insert(
                key.to_string(),
                parsed.unwrap_or_else(|| serde_json::Value::String(value.to_string())),
            );
        }

        if args.is_empty() {
            if let Some(first_json) = extract_json_values(body).into_iter().next() {
                match first_json {
                    serde_json::Value::Object(obj) => args = obj,
                    other => {
                        args.insert("value".to_string(), other);
                    }
                }
            } else if !body.is_empty() {
                args.insert(
                    "content".to_string(),
                    serde_json::Value::String(body.to_string()),
                );
            }
        }

        calls.push(ParsedToolCall {
            name: name.to_string(),
            arguments: serde_json::Value::Object(args),
            tool_call_id: None,
        });
    }

    if calls.is_empty() {
        return None;
    }

    let after = response[last_end..].trim();
    if !after.is_empty() {
        text_parts.push(after.to_string());
    }

    let text = text_parts
        .join("\n")
        .replace("<minimax:tool_call>", "")
        .replace("</minimax:tool_call>", "")
        .replace("<minimax:toolcall>", "")
        .replace("</minimax:toolcall>", "")
        .trim()
        .to_string();

    Some((text, calls))
}

// ── Tag Constants ─────────────────────────────────────────────────────────

const TOOL_CALL_OPEN_TAGS: [&str; 6] = [
    "<tool_call>",
    "<toolcall>",
    "<tool-call>",
    "<invoke>",
    "<minimax:tool_call>",
    "<minimax:toolcall>",
];

const TOOL_CALL_CLOSE_TAGS: [&str; 6] = [
    "</tool_call>",
    "</toolcall>",
    "</tool-call>",
    "</invoke>",
    "</minimax:tool_call>",
    "</minimax:toolcall>",
];

fn find_first_tag<'a>(haystack: &str, tags: &'a [&'a str]) -> Option<(usize, &'a str)> {
    tags.iter()
        .filter_map(|tag| haystack.find(tag).map(|idx| (idx, *tag)))
        .min_by_key(|(idx, _)| *idx)
}

fn matching_tool_call_close_tag(open_tag: &str) -> Option<&'static str> {
    match open_tag {
        "<tool_call>" => Some("</tool_call>"),
        "<toolcall>" => Some("</toolcall>"),
        "<tool-call>" => Some("</tool-call>"),
        "<invoke>" => Some("</invoke>"),
        "<minimax:tool_call>" => Some("</minimax:tool_call>"),
        "<minimax:toolcall>" => Some("</minimax:toolcall>"),
        _ => None,
    }
}

// ── JSON Extraction ───────────────────────────────────────────────────────

fn extract_first_json_value_with_end(input: &str) -> Option<(serde_json::Value, usize)> {
    let trimmed = input.trim_start();
    let trim_offset = input.len().saturating_sub(trimmed.len());

    for (byte_idx, ch) in trimmed.char_indices() {
        if ch != '{' && ch != '[' {
            continue;
        }

        let slice = &trimmed[byte_idx..];
        let mut stream = serde_json::Deserializer::from_str(slice).into_iter::<serde_json::Value>();
        if let Some(Ok(value)) = stream.next() {
            let consumed = stream.byte_offset();
            if consumed > 0 {
                return Some((value, trim_offset + byte_idx + consumed));
            }
        }
    }

    None
}

fn strip_leading_close_tags(mut input: &str) -> &str {
    loop {
        let trimmed = input.trim_start();
        if !trimmed.starts_with("</") {
            return trimmed;
        }

        let Some(close_end) = trimmed.find('>') else {
            return "";
        };
        input = &trimmed[close_end + 1..];
    }
}

/// Extract JSON values from a string.
///
/// # Security Warning
///
/// This function extracts ANY JSON objects/arrays from the input. It MUST only
/// be used on content that is already trusted to be from the LLM, such as
/// content inside `<invoke>` tags where the LLM has explicitly indicated intent
/// to make a tool call. Do NOT use this on raw user input or content that
/// could contain prompt injection payloads.
pub(crate) fn extract_json_values(input: &str) -> Vec<serde_json::Value> {
    let mut values = Vec::new();
    let trimmed = input.trim();
    if trimmed.is_empty() {
        return values;
    }

    if let Ok(value) = serde_json::from_str::<serde_json::Value>(trimmed) {
        values.push(value);
        return values;
    }

    let char_positions: Vec<(usize, char)> = trimmed.char_indices().collect();
    let mut idx = 0;
    while idx < char_positions.len() {
        let (byte_idx, ch) = char_positions[idx];
        if ch == '{' || ch == '[' {
            let slice = &trimmed[byte_idx..];
            let mut stream =
                serde_json::Deserializer::from_str(slice).into_iter::<serde_json::Value>();
            if let Some(Ok(value)) = stream.next() {
                let consumed = stream.byte_offset();
                if consumed > 0 {
                    values.push(value);
                    let next_byte = byte_idx + consumed;
                    while idx < char_positions.len() && char_positions[idx].0 < next_byte {
                        idx += 1;
                    }
                    continue;
                }
            }
        }
        idx += 1;
    }

    values
}

/// Find the end position of a JSON object by tracking balanced braces.
fn find_json_end(input: &str) -> Option<usize> {
    let trimmed = input.trim_start();
    let offset = input.len() - trimmed.len();

    if !trimmed.starts_with('{') {
        return None;
    }

    let mut depth = 0;
    let mut in_string = false;
    let mut escape_next = false;

    for (i, ch) in trimmed.char_indices() {
        if escape_next {
            escape_next = false;
            continue;
        }

        match ch {
            '\\' if in_string => escape_next = true,
            '"' => in_string = !in_string,
            '{' if !in_string => depth += 1,
            '}' if !in_string => {
                depth -= 1;
                if depth == 0 {
                    return Some(offset + i + ch.len_utf8());
                }
            }
            _ => {}
        }
    }

    None
}

// ── XML Attribute / Perl / FunctionCall Parsers ───────────────────────────

/// Parse XML attribute-style tool calls from response text.
fn parse_xml_attribute_tool_calls(response: &str) -> Vec<ParsedToolCall> {
    let mut calls = Vec::new();

    static INVOKE_RE: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(r#"(?s)<invoke\s+name="([^"]+)"[^>]*>(.*?)</invoke>"#).unwrap()
    });

    static PARAM_RE: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(r#"<parameter\s+name="([^"]+)"[^>]*>([^<]*)</parameter>"#).unwrap()
    });

    for cap in INVOKE_RE.captures_iter(response) {
        let tool_name = cap.get(1).map(|m| m.as_str()).unwrap_or("");
        let inner = cap.get(2).map(|m| m.as_str()).unwrap_or("");

        if tool_name.is_empty() {
            continue;
        }

        let mut arguments = serde_json::Map::new();

        for param_cap in PARAM_RE.captures_iter(inner) {
            let param_name = param_cap.get(1).map(|m| m.as_str()).unwrap_or("");
            let param_value = param_cap.get(2).map(|m| m.as_str()).unwrap_or("");

            if !param_name.is_empty() {
                arguments.insert(
                    param_name.to_string(),
                    serde_json::Value::String(param_value.to_string()),
                );
            }
        }

        if !arguments.is_empty() {
            calls.push(ParsedToolCall {
                name: map_tool_name_alias(tool_name).to_string(),
                arguments: serde_json::Value::Object(arguments),
                tool_call_id: None,
            });
        }
    }

    calls
}

/// Parse Perl/hash-ref style tool calls from response text.
pub(crate) fn parse_perl_style_tool_calls(response: &str) -> Vec<ParsedToolCall> {
    let mut calls = Vec::new();

    static PERL_RE: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(r"(?s)TOOL_CALL\s*\{(.+?)\}\}\s*/TOOL_CALL").unwrap());

    static TOOL_NAME_RE: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(r#"tool\s*=>\s*"([^"]+)""#).unwrap());

    static ARGS_BLOCK_RE: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(r"(?s)args\s*=>\s*\{(.+?)\}").unwrap());

    static ARGS_RE: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(r#"--(\w+)\s+"([^"]+)""#).unwrap());

    for cap in PERL_RE.captures_iter(response) {
        let content = cap.get(1).map(|m| m.as_str()).unwrap_or("");

        let tool_name = TOOL_NAME_RE
            .captures(content)
            .and_then(|c| c.get(1))
            .map(|m| m.as_str())
            .unwrap_or("");

        if tool_name.is_empty() {
            continue;
        }

        let args_block = ARGS_BLOCK_RE
            .captures(content)
            .and_then(|c| c.get(1))
            .map(|m| m.as_str())
            .unwrap_or("");

        let mut arguments = serde_json::Map::new();

        for arg_cap in ARGS_RE.captures_iter(args_block) {
            let key = arg_cap.get(1).map(|m| m.as_str()).unwrap_or("");
            let value = arg_cap.get(2).map(|m| m.as_str()).unwrap_or("");

            if !key.is_empty() {
                arguments.insert(
                    key.to_string(),
                    serde_json::Value::String(value.to_string()),
                );
            }
        }

        if !arguments.is_empty() {
            calls.push(ParsedToolCall {
                name: map_tool_name_alias(tool_name).to_string(),
                arguments: serde_json::Value::Object(arguments),
                tool_call_id: None,
            });
        }
    }

    calls
}

/// Parse FunctionCall-style tool calls from response text.
fn parse_function_call_tool_calls(response: &str) -> Vec<ParsedToolCall> {
    let mut calls = Vec::new();

    static FUNC_RE: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(r"(?s)<FunctionCall>\s*(\w+)\s*<code>([^<]+)</code>\s*</FunctionCall>").unwrap()
    });

    for cap in FUNC_RE.captures_iter(response) {
        let tool_name = cap.get(1).map(|m| m.as_str()).unwrap_or("");
        let args_text = cap.get(2).map(|m| m.as_str()).unwrap_or("");

        if tool_name.is_empty() {
            continue;
        }

        let mut arguments = serde_json::Map::new();
        for line in args_text.lines() {
            let line = line.trim();
            if let Some(pos) = line.find('>') {
                let key = line[..pos].trim();
                let value = line[pos + 1..].trim();
                if !key.is_empty() && !value.is_empty() {
                    arguments.insert(
                        key.to_string(),
                        serde_json::Value::String(value.to_string()),
                    );
                }
            }
        }

        if !arguments.is_empty() {
            calls.push(ParsedToolCall {
                name: map_tool_name_alias(tool_name).to_string(),
                arguments: serde_json::Value::Object(arguments),
                tool_call_id: None,
            });
        }
    }

    calls
}

// ── Tool Name Mapping ─────────────────────────────────────────────────────

/// Map tool name aliases from various LLM providers to ZeroClaw tool names.
pub(crate) fn map_tool_name_alias(tool_name: &str) -> &str {
    match tool_name {
        "shell" | "bash" | "sh" | "exec" | "command" | "cmd" | "browser_open" | "browser"
        | "web_search" => "shell",
        "send_message" | "sendmessage" => "message_send",
        "fileread" | "file_read" | "readfile" | "read_file" | "file" => "file_read",
        "filewrite" | "file_write" | "writefile" | "write_file" => "file_write",
        "filelist" | "file_list" | "listfiles" | "list_files" => "file_list",
        "memoryrecall" | "memory_recall" | "recall" | "memrecall" => "memory_recall",
        "memorystore" | "memory_store" | "store" | "memstore" => "memory_store",
        "memoryforget" | "memory_forget" | "forget" | "memforget" => "memory_forget",
        "http_request" | "http" | "fetch" | "curl" | "wget" => "http_request",
        _ => tool_name,
    }
}

pub(crate) fn build_curl_command(url: &str) -> Option<String> {
    if !(url.starts_with("http://") || url.starts_with("https://")) {
        return None;
    }

    if url.chars().any(char::is_whitespace) {
        return None;
    }

    let escaped = url.replace('\'', r"'\\''");
    Some(format!("curl -s '{escaped}'"))
}

/// Return the canonical default parameter name for a tool.
pub(crate) fn default_param_for_tool(tool: &str) -> &'static str {
    match tool {
        "shell" | "bash" | "sh" | "exec" | "command" | "cmd" => "command",
        "file_read" | "fileread" | "readfile" | "read_file" | "file" | "file_write"
        | "filewrite" | "writefile" | "write_file" | "file_edit" | "fileedit" | "editfile"
        | "edit_file" | "file_list" | "filelist" | "listfiles" | "list_files" => "path",
        "memory_recall" | "memoryrecall" | "recall" | "memrecall" | "memory_forget"
        | "memoryforget" | "forget" | "memforget" => "query",
        "memory_store" | "memorystore" | "store" | "memstore" => "content",
        "http_request" | "http" | "fetch" | "curl" | "wget" | "browser_open" | "browser"
        | "web_search" => "url",
        _ => "input",
    }
}

// ── GLM-Style Parsing ─────────────────────────────────────────────────────

pub(crate) fn parse_glm_style_tool_calls(
    text: &str,
) -> Vec<(String, serde_json::Value, Option<String>)> {
    let mut calls = Vec::new();

    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }

        // Format: tool_name/param>value or tool_name/{json}
        if let Some(pos) = line.find('/') {
            let tool_part = &line[..pos];
            let rest = &line[pos + 1..];

            if tool_part.chars().all(|c| c.is_alphanumeric() || c == '_') {
                let tool_name = map_tool_name_alias(tool_part);

                if let Some(gt_pos) = rest.find('>') {
                    let param_name = rest[..gt_pos].trim();
                    let value = rest[gt_pos + 1..].trim();

                    let arguments = match tool_name {
                        "shell" => {
                            if param_name == "url" {
                                let Some(command) = build_curl_command(value) else {
                                    continue;
                                };
                                serde_json::json!({ "command": command })
                            } else if value.starts_with("http://") || value.starts_with("https://")
                            {
                                if let Some(command) = build_curl_command(value) {
                                    serde_json::json!({ "command": command })
                                } else {
                                    serde_json::json!({ "command": value })
                                }
                            } else {
                                serde_json::json!({ "command": value })
                            }
                        }
                        "http_request" => {
                            serde_json::json!({"url": value, "method": "GET"})
                        }
                        _ => serde_json::json!({ param_name: value }),
                    };

                    calls.push((tool_name.to_string(), arguments, Some(line.to_string())));
                    continue;
                }

                if rest.starts_with('{') {
                    if let Ok(json_args) = serde_json::from_str::<serde_json::Value>(rest) {
                        calls.push((tool_name.to_string(), json_args, Some(line.to_string())));
                    }
                }
            }
        }

        // Plain URL
        if let Some(command) = build_curl_command(line) {
            calls.push((
                "shell".to_string(),
                serde_json::json!({ "command": command }),
                Some(line.to_string()),
            ));
        }
    }

    calls
}

/// Parse GLM-style shortened tool call bodies found inside `<tool_call>` tags.
pub(crate) fn parse_glm_shortened_body(body: &str) -> Option<ParsedToolCall> {
    let body = body.trim();
    if body.is_empty() {
        return None;
    }

    let function_style = body.find('(').and_then(|open| {
        if body.ends_with(')') && open > 0 {
            Some((body[..open].trim(), body[open + 1..body.len() - 1].trim()))
        } else {
            None
        }
    });

    let (tool_raw, value_part) = if let Some((tool, args)) = function_style {
        (tool, args)
    } else if body.contains("=\"") {
        let split_pos = body.find(|c: char| c.is_whitespace()).unwrap_or(body.len());
        let tool = body[..split_pos].trim();
        let attrs = body[split_pos..]
            .trim()
            .trim_end_matches("/>")
            .trim_end_matches('>')
            .trim_end_matches('/')
            .trim();
        (tool, attrs)
    } else if let Some(gt_pos) = body.find('>') {
        let tool = body[..gt_pos].trim();
        let value = body[gt_pos + 1..].trim();
        let value = value.trim_end_matches("/>").trim_end_matches('/').trim();
        (tool, value)
    } else {
        return None;
    };

    let tool_raw = tool_raw.trim_end_matches(|c: char| c.is_whitespace());
    if tool_raw.is_empty() || !tool_raw.chars().all(|c| c.is_alphanumeric() || c == '_') {
        return None;
    }

    let tool_name = map_tool_name_alias(tool_raw);

    // Try attribute-style: `key="value" key2="value2"`
    if value_part.contains("=\"") {
        let mut args = serde_json::Map::new();
        let mut rest = value_part;
        while let Some(eq_pos) = rest.find("=\"") {
            let key_start = rest[..eq_pos]
                .rfind(|c: char| c.is_whitespace())
                .map(|p| p + 1)
                .unwrap_or(0);
            let key = rest[key_start..eq_pos]
                .trim()
                .trim_matches(|c: char| c == ',' || c == ';');
            let after_quote = &rest[eq_pos + 2..];
            if let Some(end_quote) = after_quote.find('"') {
                let value = &after_quote[..end_quote];
                if !key.is_empty() {
                    args.insert(
                        key.to_string(),
                        serde_json::Value::String(value.to_string()),
                    );
                }
                rest = &after_quote[end_quote + 1..];
            } else {
                break;
            }
        }
        if !args.is_empty() {
            return Some(ParsedToolCall {
                name: tool_name.to_string(),
                arguments: serde_json::Value::Object(args),
                tool_call_id: None,
            });
        }
    }

    // Try YAML-style multi-line
    if value_part.contains('\n') {
        let mut args = serde_json::Map::new();
        for line in value_part.lines() {
            let line = line.trim();
            if line.is_empty() {
                continue;
            }
            if let Some(colon_pos) = line.find(':') {
                let key = line[..colon_pos].trim();
                let value = line[colon_pos + 1..].trim();
                if !key.is_empty() && !value.is_empty() {
                    let json_value = match value {
                        "true" | "yes" => serde_json::Value::Bool(true),
                        "false" | "no" => serde_json::Value::Bool(false),
                        _ => serde_json::Value::String(value.to_string()),
                    };
                    args.insert(key.to_string(), json_value);
                }
            }
        }
        if !args.is_empty() {
            return Some(ParsedToolCall {
                name: tool_name.to_string(),
                arguments: serde_json::Value::Object(args),
                tool_call_id: None,
            });
        }
    }

    // Single-value shortened: `tool>value`
    if !value_part.is_empty() {
        let param = default_param_for_tool(tool_raw);
        let arguments = match tool_name {
            "shell" => {
                if value_part.starts_with("http://") || value_part.starts_with("https://") {
                    if let Some(cmd) = build_curl_command(value_part) {
                        serde_json::json!({ "command": cmd })
                    } else {
                        serde_json::json!({ "command": value_part })
                    }
                } else {
                    serde_json::json!({ "command": value_part })
                }
            }
            "http_request" => serde_json::json!({"url": value_part, "method": "GET"}),
            _ => serde_json::json!({ param: value_part }),
        };
        return Some(ParsedToolCall {
            name: tool_name.to_string(),
            arguments,
            tool_call_id: None,
        });
    }

    None
}

// ── Main Parse Entry Points ───────────────────────────────────────────────

/// Parse tool calls from an LLM response that uses XML-style function calling.
///
/// Also supports JSON with `tool_calls` array from OpenAI-format responses.
pub(crate) fn parse_tool_calls(response: &str) -> (String, Vec<ParsedToolCall>) {
    let mut text_parts = Vec::new();
    let mut calls = Vec::new();
    let mut remaining = response;

    // First, try to parse as OpenAI-style JSON response with tool_calls array
    if let Ok(json_value) = serde_json::from_str::<serde_json::Value>(response.trim()) {
        calls = parse_tool_calls_from_json_value(&json_value);
        if !calls.is_empty() {
            if let Some(content) = json_value.get("content").and_then(|v| v.as_str()) {
                if !content.trim().is_empty() {
                    text_parts.push(content.trim().to_string());
                }
            }
            return (text_parts.join("\n"), calls);
        }
    }

    if let Some((minimax_text, minimax_calls)) = parse_minimax_invoke_calls(response) {
        if !minimax_calls.is_empty() {
            return (minimax_text, minimax_calls);
        }
    }

    // Fall back to XML-style tool-call tag parsing.
    while let Some((start, open_tag)) = find_first_tag(remaining, &TOOL_CALL_OPEN_TAGS) {
        let before = &remaining[..start];
        if !before.trim().is_empty() {
            text_parts.push(before.trim().to_string());
        }

        let Some(close_tag) = matching_tool_call_close_tag(open_tag) else {
            break;
        };

        let after_open = &remaining[start + open_tag.len()..];
        if let Some(close_idx) = after_open.find(close_tag) {
            let inner = &after_open[..close_idx];
            let mut parsed_any = false;

            let json_values = extract_json_values(inner);
            for value in json_values {
                let parsed_calls = parse_tool_calls_from_json_value(&value);
                if !parsed_calls.is_empty() {
                    parsed_any = true;
                    calls.extend(parsed_calls);
                }
            }

            if !parsed_any {
                if let Some(xml_calls) = parse_xml_tool_calls(inner) {
                    calls.extend(xml_calls);
                    parsed_any = true;
                }
            }

            if !parsed_any {
                if let Some(glm_call) = parse_glm_shortened_body(inner) {
                    calls.push(glm_call);
                    parsed_any = true;
                }
            }

            if !parsed_any {
                tracing::warn!(
                    "Malformed <tool_call>: expected tool-call object in tag body (JSON/XML/GLM)"
                );
            }

            remaining = &after_open[close_idx + close_tag.len()..];
        } else {
            let mut resolved = false;
            if let Some((cross_idx, cross_tag)) = find_first_tag(after_open, &TOOL_CALL_CLOSE_TAGS)
            {
                let inner = &after_open[..cross_idx];
                let mut parsed_any = false;

                let json_values = extract_json_values(inner);
                for value in json_values {
                    let parsed_calls = parse_tool_calls_from_json_value(&value);
                    if !parsed_calls.is_empty() {
                        parsed_any = true;
                        calls.extend(parsed_calls);
                    }
                }

                if !parsed_any {
                    if let Some(xml_calls) = parse_xml_tool_calls(inner) {
                        calls.extend(xml_calls);
                        parsed_any = true;
                    }
                }

                if !parsed_any {
                    if let Some(glm_call) = parse_glm_shortened_body(inner) {
                        calls.push(glm_call);
                        parsed_any = true;
                    }
                }

                if parsed_any {
                    remaining = &after_open[cross_idx + cross_tag.len()..];
                    resolved = true;
                }
            }

            if resolved {
                continue;
            }

            if let Some(json_end) = find_json_end(after_open) {
                if let Ok(value) =
                    serde_json::from_str::<serde_json::Value>(&after_open[..json_end])
                {
                    let parsed_calls = parse_tool_calls_from_json_value(&value);
                    if !parsed_calls.is_empty() {
                        calls.extend(parsed_calls);
                        remaining = strip_leading_close_tags(&after_open[json_end..]);
                        continue;
                    }
                }
            }

            if let Some((value, consumed_end)) = extract_first_json_value_with_end(after_open) {
                let parsed_calls = parse_tool_calls_from_json_value(&value);
                if !parsed_calls.is_empty() {
                    calls.extend(parsed_calls);
                    remaining = strip_leading_close_tags(&after_open[consumed_end..]);
                    continue;
                }
            }

            let glm_input = after_open.trim();
            if let Some(glm_call) = parse_glm_shortened_body(glm_input) {
                calls.push(glm_call);
                remaining = "";
                continue;
            }

            remaining = &remaining[start..];
            break;
        }
    }

    // Markdown code blocks with tool_call language
    if calls.is_empty() {
        static MD_TOOL_CALL_RE: LazyLock<Regex> = LazyLock::new(|| {
            Regex::new(
                r"(?s)```(?:tool[_-]?call|invoke)\s*\n(.*?)(?:```|</tool[_-]?call>|</toolcall>|</invoke>|</minimax:toolcall>)",
            )
            .unwrap()
        });
        let mut md_text_parts: Vec<String> = Vec::new();
        let mut last_end = 0;

        for cap in MD_TOOL_CALL_RE.captures_iter(response) {
            let full_match = cap.get(0).unwrap();
            let before = &response[last_end..full_match.start()];
            if !before.trim().is_empty() {
                md_text_parts.push(before.trim().to_string());
            }
            let inner = &cap[1];
            let json_values = extract_json_values(inner);
            for value in json_values {
                let parsed_calls = parse_tool_calls_from_json_value(&value);
                calls.extend(parsed_calls);
            }
            last_end = full_match.end();
        }

        if !calls.is_empty() {
            let after = &response[last_end..];
            if !after.trim().is_empty() {
                md_text_parts.push(after.trim().to_string());
            }
            text_parts = md_text_parts;
            remaining = "";
        }
    }

    // ```tool <name> format (e.g., xAI grok)
    if calls.is_empty() {
        static MD_TOOL_NAME_RE: LazyLock<Regex> =
            LazyLock::new(|| Regex::new(r"(?s)```tool\s+(\w+)\s*\n(.*?)(?:```|$)").unwrap());
        let mut md_text_parts: Vec<String> = Vec::new();
        let mut last_end = 0;

        for cap in MD_TOOL_NAME_RE.captures_iter(response) {
            let full_match = cap.get(0).unwrap();
            let before = &response[last_end..full_match.start()];
            if !before.trim().is_empty() {
                md_text_parts.push(before.trim().to_string());
            }
            let tool_name = &cap[1];
            let inner = &cap[2];

            let json_values = extract_json_values(inner);
            if json_values.is_empty() {
                tracing::warn!(
                    tool_name = %tool_name,
                    inner = %inner.chars().take(100).collect::<String>(),
                    "Found ```tool <name> block but could not parse JSON arguments"
                );
            } else {
                for value in json_values {
                    let arguments = if value.is_object() {
                        value
                    } else {
                        serde_json::Value::Object(serde_json::Map::new())
                    };
                    calls.push(ParsedToolCall {
                        name: tool_name.to_string(),
                        arguments,
                        tool_call_id: None,
                    });
                }
            }
            last_end = full_match.end();
        }

        if !calls.is_empty() {
            let after = &response[last_end..];
            if !after.trim().is_empty() {
                md_text_parts.push(after.trim().to_string());
            }
            text_parts = md_text_parts;
            remaining = "";
        }
    }

    // XML attribute-style tool calls
    if calls.is_empty() {
        let xml_calls = parse_xml_attribute_tool_calls(remaining);
        if !xml_calls.is_empty() {
            let mut cleaned_text = remaining.to_string();
            for call in xml_calls {
                calls.push(call);
                if let Some(start) = cleaned_text.find("<minimax:toolcall>") {
                    if let Some(end) = cleaned_text.find("</minimax:toolcall>") {
                        let end_pos = end + "</minimax:toolcall>".len();
                        if end_pos <= cleaned_text.len() {
                            cleaned_text =
                                format!("{}{}", &cleaned_text[..start], &cleaned_text[end_pos..]);
                        }
                    }
                }
            }
            if !cleaned_text.trim().is_empty() {
                text_parts.push(cleaned_text.trim().to_string());
            }
            remaining = "";
        }
    }

    // Perl/hash-ref style tool calls
    if calls.is_empty() {
        let perl_calls = parse_perl_style_tool_calls(remaining);
        if !perl_calls.is_empty() {
            let mut cleaned_text = remaining.to_string();
            for call in perl_calls {
                calls.push(call);
                while let Some(start) = cleaned_text.find("TOOL_CALL") {
                    if let Some(end) = cleaned_text.find("/TOOL_CALL") {
                        let end_pos = end + "/TOOL_CALL".len();
                        if end_pos <= cleaned_text.len() {
                            cleaned_text =
                                format!("{}{}", &cleaned_text[..start], &cleaned_text[end_pos..]);
                        }
                    } else {
                        break;
                    }
                }
            }
            if !cleaned_text.trim().is_empty() {
                text_parts.push(cleaned_text.trim().to_string());
            }
            remaining = "";
        }
    }

    // <FunctionCall> style
    if calls.is_empty() {
        let func_calls = parse_function_call_tool_calls(remaining);
        if !func_calls.is_empty() {
            let mut cleaned_text = remaining.to_string();
            for call in func_calls {
                calls.push(call);
                while let Some(start) = cleaned_text.find("<FunctionCall>") {
                    if let Some(end) = cleaned_text.find("</FunctionCall>") {
                        let end_pos = end + "</FunctionCall>".len();
                        if end_pos <= cleaned_text.len() {
                            cleaned_text =
                                format!("{}{}", &cleaned_text[..start], &cleaned_text[end_pos..]);
                        }
                    } else {
                        break;
                    }
                }
            }
            if !cleaned_text.trim().is_empty() {
                text_parts.push(cleaned_text.trim().to_string());
            }
            remaining = "";
        }
    }

    // GLM-style tool calls
    if calls.is_empty() {
        let glm_calls = parse_glm_style_tool_calls(remaining);
        if !glm_calls.is_empty() {
            let mut cleaned_text = remaining.to_string();
            for (name, args, raw) in &glm_calls {
                calls.push(ParsedToolCall {
                    name: name.clone(),
                    arguments: args.clone(),
                    tool_call_id: None,
                });
                if let Some(r) = raw {
                    cleaned_text = cleaned_text.replace(r, "");
                }
            }
            if !cleaned_text.trim().is_empty() {
                text_parts.push(cleaned_text.trim().to_string());
            }
            remaining = "";
        }
    }

    // SECURITY: We do NOT fall back to extracting arbitrary JSON from the response.

    // Remaining text after last tool call
    if !remaining.trim().is_empty() {
        text_parts.push(remaining.trim().to_string());
    }

    (text_parts.join("\n"), calls)
}

pub(crate) fn detect_tool_call_parse_issue(
    response: &str,
    parsed_calls: &[ParsedToolCall],
) -> Option<String> {
    if !parsed_calls.is_empty() {
        return None;
    }

    let trimmed = response.trim();
    if trimmed.is_empty() {
        return None;
    }

    let looks_like_tool_payload = trimmed.contains("<tool_call")
        || trimmed.contains("<toolcall")
        || trimmed.contains("<tool-call")
        || trimmed.contains("```tool_call")
        || trimmed.contains("```toolcall")
        || trimmed.contains("```tool-call")
        || trimmed.contains("```tool file_")
        || trimmed.contains("```tool shell")
        || trimmed.contains("```tool web_")
        || trimmed.contains("```tool memory_")
        || trimmed.contains("```tool ")
        || trimmed.contains("\"tool_calls\"")
        || trimmed.contains("TOOL_CALL")
        || trimmed.contains("<FunctionCall>");

    if looks_like_tool_payload {
        Some("response resembled a tool-call payload but no valid tool call could be parsed".into())
    } else {
        None
    }
}

pub(crate) fn parse_structured_tool_calls(tool_calls: &[ToolCall]) -> Vec<ParsedToolCall> {
    tool_calls
        .iter()
        .map(|call| ParsedToolCall {
            name: call.name.clone(),
            arguments: serde_json::from_str::<serde_json::Value>(&call.arguments)
                .unwrap_or_else(|_| serde_json::Value::Object(serde_json::Map::new())),
            tool_call_id: Some(call.id.clone()),
        })
        .collect()
}
