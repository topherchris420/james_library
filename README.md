## 🚀 open-source (beta) R.A.I.N. Lab

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
