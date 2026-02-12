# R.A.I.N. Lab: AI Agent Team

James Library is a research-focused platform for **RAG (Retrieval-Augmented Generation) AI agents**.

The system is designed around a **team meeting style workflow** where multiple agents converse with each other to analyze topics, compare sources, and build shared conclusions.

## What this project does

- Gives AI agents access to a memory of research papers and indexed knowledge.
- Uses retrieval to ground agent responses in available papers and references.
- Allows agents to access the internet for up-to-date context when needed.
- Supports multi-agent discussion where agents collaborate like a meeting team.

## Core idea

Instead of a single assistant response, James Library enables coordinated agent conversations that combine:

1. **Long-term paper memory** (research corpus knowledge),
2. **Live internet access** (current information), and
3. **Collaborative dialogue** (team-style reasoning).

This makes it easier to produce research-oriented outputs that are both context-rich and grounded in sources.

## Quick terminal setup (LM Studio)

If you are running LM Studio in terminal mode, these scripts now support environment-based defaults:

- `LM_STUDIO_MODEL` (default: `qwen2.5-coder-7b-instruct`)
- `LM_STUDIO_BASE_URL` (default: `http://127.0.0.1:1234/v1`)
- `JAMES_LIBRARY_PATH` (used by `chat_with_james.py`, defaults to this repo folder)
- `RAIN_RECURSIVE_INTELLECT` (`1`/`0`, default enabled)
- `RAIN_RECURSIVE_DEPTH` (default: `2`)

Example:

```bash
export LM_STUDIO_MODEL=qwen2.5-coder-7b-instruct
export LM_STUDIO_BASE_URL=http://127.0.0.1:1234/v1
python rain_lab_meeting_chat_version.py --library . --topic "your research topic" --recursive-depth 2
```

Recursive intellect means each agent can do internal critique+revision passes before speaking, improving grounding, novelty, and clarity.

### Unified launcher (recommended)

Use one command and choose backend mode:

```bash
python rain_lab.py --mode chat --topic "your research topic"
python rain_lab.py --mode rlm --topic "your research topic"
```

You can pass backend-specific flags after `--`:

```bash
python rain_lab.py --mode chat --topic "your topic" -- --recursive-depth 2 --no-web
python rain_lab.py --mode rlm --topic "your topic" -- --no-web
```

