<p align="center">
  <img src="assets/rain_lab_logo.png" alt="R.A.I.N. Lab Banner" width="100%" />
</p>

<h1 align="center">🧪 R.A.I.N. Lab</h1>

<p align="center">
  <strong>
    Local-first multi-agent AI research lab with recursive reasoning, source-grounded memory, and sovereign workflows.
  </strong>
</p>

<p align="center">
  <a href="https://github.com/">
    <img src="https://img.shields.io/badge/website-open--source-3ecf8e?style=flat-square" alt="Website" />
  </a>
  <img src="https://img.shields.io/badge/python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/framework-Multi--Agent-8A2BE2?style=flat-square" alt="Framework" />
  <img src="https://img.shields.io/badge/deploy-Vers3Dynamics-0A66C2?style=flat-square" alt="Deploy" />
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="License" />
</p>

<p align="center">
  R.A.I.N. Lab (Recursive Architecture of Intelligent Nexus) began as a local skunkworks experiment:
  what happens when AI agents are built as research partners instead of a single chatbot?
</p>

<p align="center">
  The result is a high-agency system where specialized AI scientists collaborate, debate, critique,
  and synthesize ideas inside your own knowledge base.
</p>

### Start Here (5 Minutes)

If this is your first time in the repo, use this sequence:

```bash
cd <where-you-downloaded it>
python rain_lab.py --mode first-run
python rain_lab.py --mode chat --topic "your first research question"
```

`--mode first-run` runs preflight checks and prints next-step commands so newcomers can get to a successful first response faster.

### Why this exists

Most AI interfaces optimize for fast answers.  
R.A.I.N. Lab optimizes for better thinking.

It combines:
- local research memory (RAG over your papers and notes),
- role-specialized agents with persistent identities,
- recursive reasoning loops for deeper critique,
- optional live web context when needed,
- and practical modes for both conversational and tool-driven workflows.

The goal is simple: wake up to sharper hypotheses, stronger reasoning, and actionable next steps.

### What makes it different

R.A.I.N. Lab is local-first and designed for sovereign operation.  
You control the models, the corpus, and the workflow.

This means you can tune for your domain, your standards, and your pace—without depending on a generic cloud personality or one-size-fits-all defaults.

### Who this is for

If you are building in deep tech, applied science, product R&D, or experimental AI systems, this repo is for you. It is especially useful when you need more than “helpful responses” and want structured, adversarial, source-grounded collaboration.

### Quick start

Run the unified launcher and choose a mode:

```bash
python rain_lab.py --mode first-run
python rain_lab.py --mode chat --topic "your research topic"
python rain_lab.py --mode rlm --topic "your research topic"
python rain_lab.py --mode compile --library .
python rain_lab.py --mode preflight
python rain_lab.py --mode backup
```

`--mode compile` builds local knowledge artifacts (`.rain_compile/`): TF-IDF, embeddings, entity graph, equation index, grounded quote spans, and contradiction candidates.

See also: [`ARCHITECTURE.md`](ARCHITECTURE.md) for a technical flow diagram of launcher + chat orchestration.

Strategic roadmap: [`PRODUCT_ROADMAP.md`](PRODUCT_ROADMAP.md) for the trust, grounding, memory-governance, and autonomous research roadmap.

### Reproducible local setup

Recommended (cross-platform):

```bash
python bootstrap_local.py
```

Windows convenience installer:

```powershell
.\INSTALL_RAIN.ps1
```

The installer prefers pinned dependency sets when present:
- `requirements-pinned.txt`
- `requirements-dev-pinned.txt`

Flexible (non-pinned) setup remains available via `requirements.txt` and `requirements-dev.txt`.

### Quick terminal setup (LM Studio)

If you are running LM Studio in terminal mode, these scripts support environment-based defaults:

- `LM_STUDIO_MODEL` (default: `qwen2.5-coder-7b-instruct`)
- `LM_STUDIO_BASE_URL` (default: `http://127.0.0.1:1234/v1`)
- `JAMES_LIBRARY_PATH` (used by `chat_with_james.py`, defaults to this repo folder)
- `RAIN_RECURSIVE_INTELLECT` (`1`/`0`, default enabled)
- `RAIN_RECURSIVE_DEPTH` (default: `2`)
- `RAIN_RECURSIVE_LIBRARY_SCAN` (`1`/`0`, default `0` for top-level-only scan)
- `RAIN_LIBRARY_EXCLUDE_DIRS` (comma-separated folder names excluded from recursive scans)
- `RAIN_STRICT_GROUNDING` (`1`/`0`, default `0`; blocks ungrounded runtime answers when enabled)
- `RAIN_MIN_GROUNDED_CONFIDENCE` (default `0.4`; strict grounding confidence threshold)
- `RAIN_RUNTIME_TIMEOUT_S` (default `120`; OpenAI-compatible call timeout)
- `RAIN_RUNTIME_RETRIES` (default `2`; retry count for transient runtime failures)
- `RAIN_RUNTIME_RETRY_BACKOFF_S` (default `0.8`; retry backoff base seconds)
- `RAIN_RUNTIME_MAX_QUERY_CHARS` (default `4000`; input safety limit)
- `RAIN_RUNTIME_JSON_RESPONSE` (`1`/`0`, default `0`; structured API-friendly output)
- `RAIN_ALLOW_EXTERNAL_TRACE_PATH` (`1`/`0`, default `0`; keep runtime trace logs inside workspace unless explicitly enabled)
- `RAIN_ALLOW_EXTERNAL_BACKUP_PATH` (`1`/`0`, default `0`; allow backup zip output outside `./backups`)

By default, recursive library scans skip vendored folders such as `openclaw-main/`, `vers3dynamics_lab/`, and `rlm-main/` to keep retrieval focused on the canonical R.A.I.N. workspace.

Recommended production-first local workflow:
1. Run `python rain_lab.py --mode preflight`
2. Enable strict grounding with `RAIN_STRICT_GROUNDING=1`
3. Start with `python rain_lab.py --mode chat --topic "..."` and monitor `meeting_archives/runtime_events.jsonl`

### Local backup snapshots

Create a workspace snapshot zip (stored in `backups/` by default):

```bash
python rain_lab.py --mode backup
```

Direct command options:

```bash
python rain_lab_backup.py --library . --json
python rain_lab_backup.py --library . --output ./backups/custom_snapshot.zip
```

By default, backup output is restricted to `./backups/` for safety. Set `RAIN_ALLOW_EXTERNAL_BACKUP_PATH=1` only if you intentionally need an external output path.

### Operations docs

- Troubleshooting: [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md)
- Backup/restore walkthrough: [`docs/BACKUP_RESTORE.md`](docs/BACKUP_RESTORE.md)
- Change history: [`CHANGELOG.md`](CHANGELOG.md)
- Release workflow: [`RELEASE_CHECKLIST.md`](RELEASE_CHECKLIST.md)

Recursive intellect means each agent can do internal critique + revision passes before speaking, improving grounding, novelty, and clarity.

### hello_os integration (agent empowerment)

`hello_os.py` is treated as a first-class research source for both launcher modes:

- **RLM mode** exposes `read_hello_os()` so agents can intentionally load and reason over the symbolic/geometric engine.
- **Chat mode** includes `hello_os.py` in context discovery so agents can cite and use its operator design directly.

### Persistent background service (OpenClaw)

To deploy `james_library` as a reboot-persistent background service, run:

```bash
python deploy.py --service-name james-library --target rain_lab.py --target-args -- --mode chat --topic "autonomous research"
```

`deploy.py` auto-detects the operating system and installs:

- Windows: NSSM service command using a headless Python executable (`pythonw.exe` when available)
- macOS: `~/Library/LaunchAgents/*.plist` with `KeepAlive=true`
- Linux: `/etc/systemd/system/*.service` with `Restart=always`

The supervisor process is `openclaw_service.py`, which runs a heartbeat every 60 seconds. It checks `tasks.json` for `restart` directives and scans `logs/*.log` for crash patterns to self-heal by restarting the target process.

### Godot retro RPG visual layer (MVP)

A Godot 4 presentation client now lives in `godot_client/` to render multi-agent conversations with a 2D pixel-art style while keeping backend conversation logic unchanged.

Run:

1. Open `godot_client/project.godot` in Godot 4.x.
2. Press Play to run `scenes/conversation_root.tscn`.
3. Press `1` (`flower_field`) or `2` (`lab`) to swap themes at runtime.

Live backend bridge + per-turn audio files:

1. Start bridge relay: `python godot_event_bridge.py --events-file meeting_archives/godot_events.jsonl`
2. Run multi-agent meeting with event/audio export enabled:
   `python rain_lab_meeting_chat_version.py --topic "your topic" --emit-visual-events --tts-audio-dir meeting_archives/tts_audio`
3. Godot client can connect by setting `use_demo_events=false` and `backend_ws_url=ws://127.0.0.1:8765` on `EventClient`.

How to add a new theme:

1. Copy a folder under `godot_client/themes/<new_theme_id>/theme.json`.
2. Keep the same schema keys (`background`, `ui`, `audio`, `agents`).
3. Emit `{"type":"theme_changed","theme_id":"<new_theme_id>"}` to switch live.

Where backend events connect:

- Event ingress: `godot_client/scripts/event_client.gd`
- Event routing: `godot_client/scripts/scene_orchestrator.gd`
- Contract doc: `godot_client/contracts/NEUTRAL_EVENT_CONTRACT.md`
- Blueprint doc: `docs/GODOT_SCENE_THEME_BLUEPRINT.md`
