#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel)"
cd "$ROOT_DIR"

DEFAULT_PYTHON_BIN="${PYTHON_BIN:-python3}"
DEFAULT_NODE_BIN="${NODE_BIN:-node}"
DEFAULT_NPM_BIN="${NPM_BIN:-npm}"

print_help() {
  cat <<'USAGE'
R.A.I.N. quality gate

Usage: bash scripts/ci/quality_gate.sh <command>

Commands:
  rust         Run Rust formatting, clippy, nextest, and build checks
  python       Install Python dependencies, then run ruff and pytest
  web          Install web dependencies, then run web build and optional lint/test scripts
  governance   Run governance checks triggered by changed docs/source/navigation files
  all          Run rust, python, web, and governance checks
USAGE
}

resolve_base_sha() {
  if [ -n "${BASE_SHA:-}" ] && git cat-file -e "${BASE_SHA}^{commit}" 2>/dev/null; then
    printf '%s\n' "$BASE_SHA"
    return 0
  fi

  if [ -n "${GITHUB_BASE_REF:-}" ] && git rev-parse --verify "origin/${GITHUB_BASE_REF}" >/dev/null 2>&1; then
    git merge-base "origin/${GITHUB_BASE_REF}" HEAD
    return 0
  fi

  for candidate in origin/main origin/master; do
    if git rev-parse --verify "$candidate" >/dev/null 2>&1; then
      git merge-base "$candidate" HEAD
      return 0
    fi
  done

  if git rev-parse --verify HEAD~1 >/dev/null 2>&1; then
    git rev-parse HEAD~1
    return 0
  fi

  return 1
}

ensure_web_dist_placeholder() {
  mkdir -p web/dist
  touch web/dist/.gitkeep
}

ensure_cargo_nextest() {
  if cargo nextest --version >/dev/null 2>&1; then
    return 0
  fi

  echo "==> installing cargo-nextest"
  cargo install cargo-nextest --locked
}

install_python_dependencies() {
  echo "==> python: upgrade pip"
  "$DEFAULT_PYTHON_BIN" -m pip install --upgrade pip

  if [ -f requirements-pinned.txt ]; then
    echo "==> python: install requirements-pinned.txt"
    "$DEFAULT_PYTHON_BIN" -m pip install -r requirements-pinned.txt
  elif [ -f requirements.txt ]; then
    echo "==> python: install requirements.txt"
    "$DEFAULT_PYTHON_BIN" -m pip install -r requirements.txt
  fi

  if [ -f requirements-dev-pinned.txt ]; then
    echo "==> python: install requirements-dev-pinned.txt"
    "$DEFAULT_PYTHON_BIN" -m pip install -r requirements-dev-pinned.txt
  elif [ -f requirements-dev.txt ]; then
    echo "==> python: install requirements-dev.txt"
    "$DEFAULT_PYTHON_BIN" -m pip install -r requirements-dev.txt
  fi

}

run_rust() {
  ensure_web_dist_placeholder
  "$DEFAULT_PYTHON_BIN" scripts/ci/repo_integrity_guard.py
  bash scripts/ci/rust_quality_gate.sh --strict
  ensure_cargo_nextest
  cargo nextest run --locked
  cargo check --all-features --locked
  cargo build --profile ci --locked
}

run_python() {
  install_python_dependencies
  export PYTHONPATH="$ROOT_DIR/python${PYTHONPATH:+:$PYTHONPATH}"
  "$DEFAULT_PYTHON_BIN" -m ruff check . --output-format=full
  "$DEFAULT_PYTHON_BIN" -m pytest tests -v -ra --tb=long

  if [ -d python/R.A.I.N._tools ]; then
    (
      cd python
      PYTHONPATH="$ROOT_DIR/python${PYTHONPATH:+:$PYTHONPATH}" "$DEFAULT_PYTHON_BIN" -m pytest tests -v -ra --tb=long
    )
  else
    echo "==> python: companion package sources not present at python/R.A.I.N._tools; skipping python/tests"
  fi
}

run_web() {
  if [ ! -f web/package.json ]; then
    echo "No web/package.json found; skipping web quality gate."
    return 0
  fi

  ensure_web_dist_placeholder
  echo "==> web: npm ci"
  "$DEFAULT_NPM_BIN" ci --prefix web

  if "$DEFAULT_NODE_BIN" -e "const pkg=require('./web/package.json'); process.exit(pkg.scripts && pkg.scripts.lint ? 0 : 1)"; then
    echo "==> web: npm run lint"
    "$DEFAULT_NPM_BIN" run lint --prefix web
  else
    echo "==> web: no lint script defined; skipping"
  fi

  if "$DEFAULT_NODE_BIN" -e "const pkg=require('./web/package.json'); process.exit(pkg.scripts && pkg.scripts.test ? 0 : 1)"; then
    echo "==> web: npm run test"
    "$DEFAULT_NPM_BIN" run test --prefix web
  else
    echo "==> web: no test script defined; skipping"
  fi

  echo "==> web: npm run build"
  "$DEFAULT_NPM_BIN" run build --prefix web
}

run_governance() {
  local base_sha
  if ! base_sha="$(resolve_base_sha)"; then
    echo "Unable to resolve a diff base; running docs parity check only."
    bash scripts/ci/docs_parity_check.sh
    return 0
  fi

  echo "==> governance: using BASE_SHA=$base_sha"
  BASE_SHA="$base_sha"
  export BASE_SHA

  local changed_files
  changed_files="$(git diff --name-only "$BASE_SHA" HEAD || true)"

  if printf '%s\n' "$changed_files" | rg -q '^(src/|README\.md$|README\.(zh-CN|ja|ru|fr|vi)\.md$|docs/README\.md$|docs/README\.(zh-CN|ja|ru|fr)\.md$|docs/i18n/vi/README\.md$|docs/SUMMARY\.md$)'; then
    bash scripts/ci/docs_parity_check.sh
    bash scripts/ci/arch_boundary_check.sh
  else
    echo "==> governance: no docs parity or architecture boundary triggers detected; skipping"
  fi

  if printf '%s\n' "$changed_files" | rg -q '(\.md$|\.mdx$|^LICENSE$|^\.github/pull_request_template\.md$)'; then
    bash scripts/ci/docs_quality_gate.sh
  else
    echo "==> governance: no docs quality triggers detected; skipping"
  fi
}

if [ $# -lt 1 ]; then
  print_help
  exit 1
fi

case "$1" in
  rust)
    run_rust
    ;;
  python)
    run_python
    ;;
  web)
    run_web
    ;;
  governance)
    run_governance
    ;;
  all)
    run_rust
    run_python
    run_web
    run_governance
    ;;
  -h|--help|help)
    print_help
    ;;
  *)
    print_help
    exit 1
    ;;
esac
