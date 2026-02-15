# Contributing to R.A.I.N. Lab

Thank you for your interest in contributing to the **Resonant Adaptive
Intelligence Network** project. This document describes the rules every
contributor—human or bot—must follow before code lands on `main`.

---

## Pull Request Policy

### Bot-generated PRs (Jules, Codex, Copilot, etc.)

| Requirement | Detail |
|---|---|
| **Human review** | At least **one human review comment** before merge. A simple "LGTM" is not sufficient—the comment must reference what was checked. |
| **CI green** | All status checks (lint, tests) must pass. |
| **Security PRs** | Must include an explicit sign-off that names the **vulnerability class** (e.g., injection, path traversal) and the **verification method** (e.g., unit test, manual audit). |
| **Commit hygiene** | Squash-merge preferred so the history stays readable. |

### Human PRs

- One approval required before merging to `main`.
- Squash-merge preferred.
- Keep PR descriptions concise: state *what* changed, *why*, and link any
  relevant issue.

### All PRs

- Must target `main` unless otherwise arranged with the Lead.
- Must not introduce regressions—existing tests must stay green.
- Large changes should be broken into reviewable chunks (< 400 lines diff
  where practical).

---

## Branch Naming

| Prefix | Use |
|---|---|
| `feat/` | New features or enhancements |
| `fix/` | Bug fixes |
| `refactor/` | Structural improvements with no behaviour change |
| `docs/` | Documentation only |
| `ci/` | CI/CD pipeline changes |

---

## Issue Templates

Use the appropriate template when opening an issue:

- **Bug** — steps to reproduce, expected vs actual, environment.
- **Feature** — problem statement, proposed mechanism, success metric.
- **Theory** — claim, supporting derivation or citation, testable prediction.

Pre-built templates live in `.github/ISSUE_TEMPLATE/`.

---

## Branch Protection (Maintainers)

The `main` branch should have these protections enabled in
**Settings → Branches → Add rule**:

- [x] Require pull request reviews: **1**
- [x] Require status checks to pass: **CI** workflow
- [x] Include administrators
- [x] Do not allow bypassing the above settings

---

## Code Style

- Python: formatted and linted with **ruff** (`ruff check .`).
- Max line length: not enforced globally (E501 ignored), but keep it
  reasonable.
- Tests live in `tests/` and run via `pytest`.

---

## Getting Started

```bash
# Clone the fork
git clone https://github.com/MultiplicityFoundation/R.A.I.N..git
cd R.A.I.N.

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Run the test suite
pytest tests/ -v

# Lint
ruff check .
```
