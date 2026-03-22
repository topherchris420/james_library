# Start Here

**One sentence:** R.A.I.N. Lab is an AI research assistant that helps you explore sound, resonance, and physics ideas without rediscovering things you already know.

**Why you need it:** You're doing research with AI. This tool makes sure your AI doesn't waste time finding "new" ideas that you already knew or that are widely known.

---

## If You Only Read One Thing

Use this command:

```bash
python rain_lab.py
```

For non-technical users, this is the **only entry point you need**. The script includes a guided wizard, first-run setup, validation checks, model listing, and chat/research modes.

You can safely ignore files like `rain_unique.py`, `james_reader.py`, `chat_with_james.py`, and other specialized scripts unless a maintainer tells you to use them.

---

## Name Guide (Plain English)

- **R.A.I.N. Lab**: the product experience you use.
- **R.A.I.N.**: the Rust runtime engine under the hood.
- **James Library**: the Python workflow collection in this repository.
- **Vers3Dynamics**: the project/organization branding.

If you're just using the tool, think of all of this as one app and start with `python rain_lab.py`.

---


## Checklist

Before first use, install:

1. **Python 3.10+**
2. **Ollama**
3. At least one model (example):
   ```bash
   ollama pull qwen2.5-coder
   ```

If you are unsure whether setup is complete, run:

```bash
python rain_lab.py --mode validate
```

---

## First-Time Onboarding Flow

For a new non-technical user:

1. Install Python and Ollama.
2. Run `python rain_lab.py --mode first-run` once.
3. Run `python rain_lab.py` and choose **Chat** or **Guided mode**.
4. If anything fails, run `python rain_lab.py --mode validate`.

---

## One Command to Start

### Any System (Recommended)
```bash
python rain_lab.py
```

That's it. Just run that command and follow the simple prompts.

---

## What Can You Do?

| When you want to... | Run this |
|---------------------|----------|
| **I'm not sure where to start** | `python rain_lab.py` (starts wizard) |
| Chat with AI about my research | `python rain_lab.py --mode chat --topic "your topic"` |
| Check if my system is ready | `python rain_lab.py --mode validate` |
| See what AI models are available | `python rain_lab.py --mode models` |
| Set everything up for the first time | `python rain_lab.py --mode first-run` |
| Run a structured research meeting | `python rain_lab.py --mode rlm --topic "your topic"` |

---

## Quick Troubleshooting

**"Python not found"**
- Download and install from [python.org](https://python.org)

**"Ollama not found"**
- Download from [ollama.ai](https://ollama.ai)

**Not sure what to do?**
- Just run `python rain_lab.py` and it will ask you what you want to do

---

## Need Help?

- **Simplest start**: Run `python rain_lab.py` and choose from the menu
- **Simple guide**: See `README_SIMPLE.md`
- **Technical details**: See `README.md`
- **Problems?**: Try `python rain_lab.py --mode validate`
