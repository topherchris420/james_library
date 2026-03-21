# Dependency Strategy

This document outlines the dependency management approach for james_library.

## Dependency Files

| File | Purpose | Use Case |
|------|---------|----------|
| `requirements.txt` | Loose versions with upper bounds | Development, exploring new features |
| `requirements-pinned.txt` | Exact pinned versions | Reproducible production installs |
| `requirements-reader.txt` | James Reader specific | Running the reader component |
| `requirements-dev.txt` | Development tools | Running tests, linting, formatting |
| `uv.lock` | uv package manager lockfile | Using uv for fast, reproducible installs |

## Version Strategy

- **Upper bounds** on main requirements.txt to prevent breaking changes from major version bumps
- **Exact pinning** in requirements-pinned.txt for CI/CD reproducibility
- **Python version-specific** constraints in pinned file (e.g., numpy, networkx)

## Installation

```bash
# Recommended for production
pip install -r requirements-pinned.txt

# For development
pip install -r requirements.txt

# Using uv (faster)
uv pip install -r requirements.txt
```

## Updating Dependencies

1. Test changes in `requirements.txt` first
2. Run full test suite
3. Update `requirements-pinned.txt` with tested versions
4. Commit both files together
5. Update `uv.lock` if using uv: `uv lock`

## Adding New Dependencies

1. Add to `requirements.txt` with appropriate version bounds
2. If stability required, also add to `requirements-pinned.txt` with exact version
3. Update this document if strategy changes