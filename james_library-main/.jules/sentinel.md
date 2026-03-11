## 2024-05-22 - [Indirect Prompt Injection via Web Search]
**Vulnerability:** Unvalidated web search results entered the agent context, allowing external content to potentially hijack the agent using prompt injection techniques (e.g., fake system prompts, recursive search commands).
**Learning:** LLM agents that consume external data must treat that data as untrusted. Simply formatting it into the prompt is dangerous if the data contains control tokens or prompt-like structures.
**Prevention:** Implement strict sanitization for all external data sources. Strip known control tokens, escape prompt delimiters (like `###`), and neutralize command triggers (like `[SEARCH:`).

## 2024-05-23 - [Direct Prompt Injection via Local Files]
**Vulnerability:** Untrusted content from local files (inbox messages, research papers) was injected directly into the LLM context without sanitization. Attackers could use control tokens (e.g., `<|im_end|>`) or fake headers (e.g., `###`) to hijack the agent's behavior.
**Learning:** File system inputs are not inherently safe. Any external data entering the prompt must be treated as untrusted, regardless of its source (web or local).
**Prevention:** Apply a unified sanitization function to ALL external inputs (web search, file reads, user messages) before adding them to the prompt context.

## 2026-02-19 - [Direct Prompt Injection via Code Execution REPL]
**Vulnerability:** The RLM mode (`rain_lab_meeting.py`) executed tools like `read_paper` and `search_web` inside a REPL without sanitizing their output before returning it to the LLM context. This allowed prompt injection attacks via malicious file content or web results.
**Learning:** Code execution environments (REPLs) that feed tool outputs back to the LLM are just as vulnerable to indirect prompt injection as standard chat loops. Any function exposed to the REPL that reads external data must sanitize it before returning.
**Prevention:** Injected a unified `sanitize_text` function into the REPL setup code and wrapped all data-fetching functions (`read_paper`, `search_web`, `read_hello_os`, `semantic_search`) to sanitize their output immediately.
