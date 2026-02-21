## 🚀 open-source (beta) R.A.I.N. Lab

![James Library](assets/james-library.svg)

R.A.I.N. Lab (Recursive Architecture of Intelligent Nexus) is open source.

This idea started as a local skunkworks experiment: what happens when agents are built as a research partner instead of a single chatbot? The result is a multi-agent, local-first system where specialized AI scientists collaborate, debate, critique, and synthesize ideas over your own knowledge base.

R.A.I.N. Lab is designed for people who want high-agency workflows: researchers, founders, engineers, and independent labs who care about sovereignty, technical depth, and iterative discovery.

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

See also: [`ARCHITECTURE.md`](ARCHITECTURE.md) for a technical flow diagram of launcher + chat orchestration.


```bash
python rain_lab.py --mode chat --topic "your research topic"
python rain_lab.py --mode rlm --topic "your research topic"

## Quick terminal setup (LM Studio)

If you are running LM Studio in terminal mode, these scripts now support environment-based defaults:

- `LM_STUDIO_MODEL` (default: `qwen2.5-coder-7b-instruct`)
- `LM_STUDIO_BASE_URL` (default: `http://127.0.0.1:1234/v1`)
- `JAMES_LIBRARY_PATH` (used by `chat_with_james.py`, defaults to this repo folder)
- `RAIN_RECURSIVE_INTELLECT` (`1`/`0`, default enabled)
- `RAIN_RECURSIVE_DEPTH` (default: `2`)


Recursive intellect means each agent can do internal critique+revision passes before speaking, improving grounding, novelty, and clarity.

### hello_os integration (agent empowerment)

`hello_os.py` is now treated as a first-class research source for both launcher modes:
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

The supervisor process is `openclaw_service.py`, which runs a heartbeat every 60 seconds.
It checks `tasks.json` for `restart` directives and scans `logs/*.log` for crash patterns to self-heal by restarting the target process.
