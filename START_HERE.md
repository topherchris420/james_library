# Start Here

**One sentence:** R.A.I.N. Lab is an AI research assistant that helps you explore sound, resonance, and physics ideas without rediscovering things you already know.

**Why you need it:** You're doing research with AI. This tool makes sure your AI doesn't waste time finding "new" ideas that you already knew or that are widely known.

---

## If You Only Read One Thing

Install once, then use this command every day:

```bash
python rain_lab.py
```

For non-technical users, this is the **only daily entry point you need**. The script opens a guided wizard, pressing Enter starts the no-setup instant demo, and every beginner/demo run updates a local showcase page in `meeting_archives/RAIN_LAB_SHOWCASE.html`.
Those runs also generate a screenshot-friendly HTML share card plus a matching poster SVG in `meeting_archives/`.

Windows users should start with `.\INSTALL_RAIN.cmd`. macOS/Linux users should start with `./install.sh`.

You can safely ignore files like `rain_unique.py`, `james_reader.py`, and other specialized scripts unless a maintainer tells you to use them. `chat_with_james.py` is used for the first installer handoff, but it is not the main product launcher.

---

## Stable Path

Start with `python rain_lab.py`. That launcher, plus the default Rust build,
is the stable core.

Integrations such as Matrix, Lark, Nostr, WhatsApp Web, hardware, and
experimental workflow automation are opt-in extensions. Treat them as add-ons,
not the baseline product.

If you need the full support boundary, see
[`docs/project/stability-tiers.md`](docs/project/stability-tiers.md).

---

## Name Guide (Plain English)

- **R.A.I.N. Lab**: the product experience you use.
- **ZeroClaw**: the Rust runtime engine under the hood.
- **James Library**: the Python workflow collection in this repository.
- **Vers3Dynamics**: the project/organization branding.

If you're just using the tool, think of all of this as one app and start with `python rain_lab.py`.

---


## Checklist

Before first use, make sure you have one supported install route:

1. **Windows**: run `.\INSTALL_RAIN.cmd`
2. **macOS/Linux**: run `./install.sh`
3. **Optional local models**: install Ollama or LM Studio if you want local inference instead of the instant demo or a hosted provider
4. **Optional hosted models**: paste an API key into the bootstrap prompt so `.env` is created for you

If you are unsure whether setup is complete, run:

```bash
python rain_lab.py --mode validate
```

---

## First-Time Onboarding Flow

For a new non-technical user:

1. Run `.\INSTALL_RAIN.cmd` on Windows, or `./install.sh` on macOS/Linux.
2. If the installer hands you off to James, use that as the welcome screen, then return to `python rain_lab.py` for the main product workflow.
3. Run `python rain_lab.py` and press Enter for the instant demo, or choose **Beginner mode**.
4. If you want to wire up local or hosted models, run `python rain_lab.py --mode first-run`.
5. After a session, open `meeting_archives/RAIN_LAB_SHOWCASE.html` to revisit recent runs, poster previews, and copy the next commands.
6. If anything fails, run `python rain_lab.py --mode validate`.

---

## One Command to Start

### Any System (Recommended)
```bash
python rain_lab.py
```

That's it. Just run that command, press Enter for the instant demo if you want the fastest path, and use the generated showcase page and poster-style share outputs to keep going.

---

## What Can You Do?

| When you want to... | Run this |
|---------------------|----------|
| **I'm not sure where to start** | `python rain_lab.py` (starts wizard) |
| **Give it one idea and let it choose for me** | `python rain_lab.py --mode beginner --topic "your idea"` |
| **Try a no-setup instant demo** | `python rain_lab.py --mode demo --preset startup-debate` |
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
- Install Ollama only if you want local-model inference. Otherwise press Enter for the instant demo or use a hosted API key in `.env`.

**Not sure what to do?**
- Just run `python rain_lab.py` and it will ask you what you want to do

---

## Need Help?

- **Simplest start**: Run `python rain_lab.py` and choose from the menu
- **Install routes**: See `README.md`
- **Technical details**: See `README.md`
- **Problems?**: Try `python rain_lab.py --mode validate`
