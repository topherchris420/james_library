# Product Boundary

R.A.I.N. Lab is a local-first research assistant that runs a structured expert-panel workflow over private context. The default product experience is the launcher plus the stable runtime needed to ask a research question, run the James/Jasmine/Luca/Elena meeting, preserve the transcript, and review the result offline.

## Stable Core

The stable core is the path a new user should be able to trust first:

- `python rain_lab.py`
- `python rain_lab.py --mode demo --preset startup-debate`
- `python rain_lab.py --mode validate`
- `python rain_lab.py --mode chat --topic "..."`
- The Rust `rain` runtime and its default provider, tool, memory, security, and gateway contracts
- Installer entry points: `INSTALL_RAIN.cmd`, `INSTALL_RAIN.ps1`, and `install.sh`
- Local meeting artifacts under `meeting_archives/`

Core changes need user-facing docs, tests or smoke coverage, and CI verification.

## Opt-In Extensions

Extensions are supported, but they should not be required for the default path:

- Messaging channels such as Slack, Telegram, Matrix, Nostr, Lark, and email
- Hardware and firmware integrations
- TRIBE v2 and other sidecar services
- Web dashboard and deployment assets
- Plugin examples and custom provider integrations

Extension changes should keep their setup isolated, avoid surprising network calls, and preserve the default local-only flow.

## Experiments And Archive Material

Experimental or archival assets may stay in the repository when they are useful for preservation, demos, or research continuity, but they must be labeled as non-core. Large generated files, benchmark data, prototype scripts, and research snapshots should not become default startup dependencies.

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
- **James Library**: the repository and Python workflow collection.
- **rain**: the Rust binary/runtime crate.
- **ZeroClaw**: legacy/runtime branding used only where existing compatibility requires it.

