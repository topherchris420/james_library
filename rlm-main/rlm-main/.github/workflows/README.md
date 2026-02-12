# GitHub Actions Workflows

This directory contains automated workflows for the RLM (Recursive Language Models) project.

## Workflows

### 1. Style (`style.yaml`)
**Purpose**: Code style checking using ruff.

**Triggers**:
- Pull requests (opened, synchronized, reopened)
- Pushes to `main` branch

**What it does**:
- Runs ruff for linting and formatting checks
- Uses configuration from `pyproject.toml`

### 2. Test (`test.yml`)
**Purpose**: Run tests with coverage.

**Triggers**:
- Pull requests
- Pushes to `main` branch

**What it does**:
- Runs tests on multiple Python versions (3.11, 3.12)
- Generates coverage report (terminal output)

**Note**: Tests that require external services (Modal, API keys) are excluded from CI runs. The following test files are skipped:
- `tests/repl/test_modal_repl.py` - Requires Modal authentication
- `tests/clients/` - Requires API keys for external LLM providers

## Setting Up

### Branch Protection
It's recommended to set up branch protection rules for your main branch:
1. Go to Settings → Branches
2. Add a rule for your main branch
3. Enable "Require status checks to pass before merging"
4. Select the CI jobs you want to require (e.g., `lint`, `test`)

## Running Tests Locally

To run tests locally the same way they run in CI:

```bash
# Install dependencies
uv pip install -e .
uv pip install pytest pytest-asyncio pytest-cov

# Run tests (excluding Modal and API-dependent tests)
python -m pytest tests/ -v \
    --ignore=tests/repl/test_modal_repl.py \
    --ignore=tests/clients/

# Run tests with coverage
python -m pytest tests/ -v \
    --ignore=tests/repl/test_modal_repl.py \
    --ignore=tests/clients/ \
    --cov=rlm \
    --cov-report=html
```

## Running Style Checks Locally

```bash
# Install ruff
uv pip install ruff

# Run linting
ruff check .

# Run formatting check
ruff format --check .

# Auto-fix linting issues
ruff check --fix .

# Auto-format code
ruff format .
```

## Customization

### Adding New Python Versions
Edit the `matrix.python-version` in `test.yml` to test on additional Python versions.

### Changing Trigger Conditions
Modify the `on:` section in the workflow files to change when workflows run.

### Adding More Checks
You can extend the workflows to include:
- Type checking with mypy or ty
- Security scanning
- Documentation building
- Package building and publishing

