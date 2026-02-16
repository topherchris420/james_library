## 2024-05-22 - [Indirect Prompt Injection via Web Search]
**Vulnerability:** Unvalidated web search results entered the agent context, allowing external content to potentially hijack the agent using prompt injection techniques (e.g., fake system prompts, recursive search commands).
**Learning:** LLM agents that consume external data must treat that data as untrusted. Simply formatting it into the prompt is dangerous if the data contains control tokens or prompt-like structures.
**Prevention:** Implement strict sanitization for all external data sources. Strip known control tokens, escape prompt delimiters (like `###`), and neutralize command triggers (like `[SEARCH:`).
