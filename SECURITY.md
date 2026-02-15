# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in R.A.I.N. Lab, report it by opening an issue on this repository:

**https://github.com/MultiplicityFoundation/R.A.I.N./issues**

### What to include

- Description of the vulnerability and its potential impact.
- Steps to reproduce or a minimal proof of concept.
- Affected file(s) and line numbers, if known.
- Suggested fix, if you have one.

### Labels

When opening a security issue, add the label `security` if available. If not, prefix the issue title with `[SECURITY]`.

### Response

- We aim to acknowledge reports within 72 hours.
- Confirmed vulnerabilities will be prioritized based on severity and patched on `main`.
- Credit will be given to reporters in the commit message unless anonymity is requested.

## Scope

This policy covers all code in the `MultiplicityFoundation/R.A.I.N.` repository, including:

- Python scripts (`rain_lab.py`, `rain_lab_meeting.py`, `rain_lab_meeting_chat_version.py`, `hello_os.py`)
- Agent soul files (`*_SOUL.md`)
- Configuration and preflight tooling (`rain_preflight_check.py`)

## Known Patterns

R.A.I.N. Lab runs local-first with a local OpenAI-compatible endpoint. Primary attack surfaces include:

- **Path manipulation** — `sys.path` modifications that could allow module shadowing (mitigated in PR #25).
- **Prompt injection** — Malicious content in loaded `.md`/`.txt` corpus files that could alter agent behavior.
- **Unvalidated web search results** — When web search is enabled, returned content enters agent context without sanitization.

## Supported Versions

| Version | Supported |
|---|---|
| `main` branch (HEAD) | Yes |
| All other branches | No |
