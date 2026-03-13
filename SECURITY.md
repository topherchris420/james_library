# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in R.A.I.N. Lab, report it by opening an issue on this repository:

**https://github.com/MultiplicityFoundation/R.A.I.N./issues**

### What to include

Include the following information in your report:

1. **Description**: A clear description of the vulnerability
2. **Impact**: The potential security impact (data exposure, privilege escalation, etc.)
3. **Reproduction Steps**: Detailed steps to reproduce the issue
4. **Affected Components**: Which parts of Phase Mirror are affected (mirror-dissonance, Terraform configs, API endpoints, etc.)
5. **Suggested Fix**: If you have one (optional but appreciated)

### Severity Classifications

| Severity | Response Time | Examples |
|----------|--------------|----------|
| **Critical** | 24-48 hours | RCE, authentication bypass, data exfiltration |
| **High** | 7 days | Privilege escalation, sensitive data exposure |
| **Medium** | 30 days | Information disclosure, CSRF |
| **Low** | 90 days | Minor information leaks, best practice violations |

### Labels

When opening a security issue, add the label `security` if available. If not, prefix the issue title with `[SECURITY]`.

### What to Expect

- **Acknowledgment**: Within 48 hours of your report
- **Initial Assessment**: Within 7 business days
- **Resolution Timeline**: Dependent on severity (see below)
- **Credit**: Public acknowledgment in release notes (unless you prefer anonymity)

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
