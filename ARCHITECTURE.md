# R.A.I.N. Lab Architecture (Launcher + Chat Mode)

This document describes how the top-level `rain_lab.py` launcher and the chat backend (`rain_lab_meeting_chat_version.py`) execute a meeting.

## High-level flow

```mermaid
sequenceDiagram
    autonumber
    participant U as User (CLI)
    participant L as rain_lab.py (launcher)
    participant C as rain_lab_meeting_chat_version.py
    participant CM as ContextManager
    participant WS as WebSearchManager
    participant OAI as Local OpenAI-compatible endpoint (LM Studio)
    participant CA as CitationAnalyzer
    participant LOG as LogManager

    U->>L: python rain_lab.py --mode chat --topic "..."
    L->>L: Parse args + map aliases
    L->>C: subprocess.run([python, rain_lab_meeting_chat_version.py, ...])

    C->>OAI: test_connection()
    OAI-->>C: small completion response

    C->>CM: Discover + load .md/.txt corpus
    CM-->>C: bounded context_block + paper_list

    alt web search enabled
        C->>WS: search(topic)
        WS-->>C: formatted web snippets (optional)
    end

    C->>LOG: initialize_log(topic, paper_count)

    loop for each turn
        C->>OAI: chat.completions.create(system+user prompt)
        OAI-->>C: draft response

        alt recursive intellect enabled
            C->>OAI: critique pass
            OAI-->>C: critique bullets
            C->>OAI: refinement pass
            OAI-->>C: revised response
        end

        C->>CA: analyze_response(response)
        CA->>CM: verify quoted text in loaded papers
        CM-->>CA: source match (or none)
        CA-->>C: citation metadata

        C->>LOG: log_statement(agent, response, metadata)
    end

    C->>LOG: finalize_log(stats)
    C-->>U: session summary + log location
```

## Key implementation details

- **Launcher/router (`rain_lab.py`)**
  - Splits known args from passthrough args (`--` support).
  - Normalizes generic flags like `--turns` into mode-specific flags.
  - Executes the selected backend script via `subprocess.run`.

- **Config-driven backend (`rain_lab_meeting_chat_version.py`)**
  - Reads defaults from environment (`LM_STUDIO_MODEL`, `LM_STUDIO_BASE_URL`, recursive settings).
  - Builds a role-specialized 4-agent team (James/Jasmine/Luca/Elena).
  - Loads a bounded local corpus into prompt context; retains full text for post-hoc citation checks.

- **Inference loop**
  - Per-turn prompt includes:
    - agent identity/soul,
    - recent transcript window,
    - mission instruction,
    - shared context block.
  - Optional recursive refinement adds critique/rewrite passes before finalizing agent output.

- **Grounding and observability**
  - Quoted spans are extracted and fuzzily verified against loaded local papers.
  - Meeting transcripts and citation metadata are written to `RAIN_LAB_MEETING_LOG.md`, with archival rotation support.

## Failure/edge behavior

- If `openai` package is missing, startup exits with install guidance.
- If local endpoint is unavailable, connection test retries and prints troubleshooting hints.
- If web search packages are missing or rate-limited, meeting proceeds with local context only.
