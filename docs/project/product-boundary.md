# Product Boundary

R.A.I.N. Lab is a local-first research assistant that runs a structured expert-panel workflow over private context. The default product experience is the launcher plus the stable runtime needed to ask a research question, run the James/Jasmine/Luca/Elena meeting, preserve the transcript, and review the result offline.

## Stable Core

The stable core is the path a new user should be able to trust first:

- `python rain_lab.py`
- `python rain_lab.py --mode demo`
- `python rain_lab.py --mode validate`
- `python rain_lab.py --mode chat --topic "..."`
- The Rust `rain` runtime and its default provider, tool, memory, security, and gateway contracts
- Installer entry points: `INSTALL_RAIN.cmd`, `INSTALL_RAIN.ps1`, and `install.sh`
- Local meeting artifacts under `meeting_archives/`

Core changes need user-facing docs, tests or smoke coverage, and CI verification.

## Citation Corpus

A quote counts as a paper citation only when the full span occurs in a file under the citation corpus. Product files are not that corpus: `README*`, `*_SOUL.md`, logs, `START_HERE*`, `CONTRIBUTING*`, `SECURITY*`, `ARCHITECTURE*`, `LICENSE*`, `docs/`, and `assets/`.

Resolution order for chat (`rain_lab_meeting_chat_version.py`), the RLM host file picker, and the offline
instant demo (`--mode demo`):

1. `--corpus` or `RAIN_CORPUS_DIR`
2. `<library>/papers` when that directory exists
3. the library root, still with the product files excluded

`--library` remains the library root (souls, meeting archives, and the default place to look for `papers/`). Point it at a papers directory only when that directory itself is the corpus and does not contain a nested `papers/` folder you did not intend to select.

`RAIN_CORPUS_INCLUDE_PRODUCT=1` opts product files back in. Session artifacts record `corpus_files` as `{path, sha256}` for the files actually loaded. `require_quotes` (default true) stores `grounded: false` and prints an ungrounded badge when a turn has no verified span. It does not print a success checkmark for that turn.

## Opt-In Extensions

Extensions are supported, but they should not be required for the default path:

- Messaging channels such as Slack, Telegram, Matrix, Nostr, Lark, and email
- Hardware and firmware integrations
- TRIBE v2 and other sidecar services
- Web dashboard and deployment assets
- Plugin examples and custom provider integrations
- R.A.I.N. Rig (`rain rig …`, `[rig]` in `config.toml`): an optional node layer
  that discovers local inference, transports, and listeners. It adds no
  listeners and no mandatory dependencies. `python rain_lab.py` never depends
  on it, and omitting `[rig]` keeps pre-Rig behavior. See [`docs/rig/`](../rig/README.md).

Extension changes should keep their setup isolated, avoid surprising network calls, and preserve the default local-only flow.

## Experiments And Archive Material

Experimental or archival assets may stay in the repository when they are useful for preservation, demos, or research continuity, but they must be labeled as non-core. Large generated files, benchmark data, prototype scripts, and research snapshots should not become default startup dependencies.

Skybridge (`src/rig/skybridge/`) is experimental: a software-only plaintext
frame codec and baseband modem with RF transmit disabled. It is not part of the
stable core.

If an experiment becomes user-facing, promote it by adding:

- a documented entry point,
- a test or smoke check,
- ownership notes,
- and a clear failure mode when optional dependencies are absent.

## Out Of Scope For The Core Path

The core product should not require:

- cloud inference,
- hosted telemetry,
- hardware devices,
- web deployment,
- social or messaging channel credentials,
- or external model sidecars.

Those capabilities are valuable extensions. They are not prerequisites for the first successful run.

## Naming Rule

Use these names consistently:

- **R.A.I.N. Lab**: the product experience.
- **James**: the lead assistant in the research meeting.
- **R.A.I.N. Rig**: the optional node layer (`rain rig`) over the runtime; never a prerequisite for the lab.
- **James Library**: the repository and Python workflow collection.
- **rain**: the Rust binary/runtime crate.
- **ZeroClaw**: legacy/runtime branding used only where existing compatibility requires it.

