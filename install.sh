#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" >/dev/null 2>&1 && pwd || pwd)"
REPO_ROOT="$SCRIPT_DIR"
PYTHON_VERSION="${RAIN_INSTALL_PYTHON_VERSION:-3.12}"
RECREATE_VENV=false
SKIP_GREET=false
BOOTSTRAP_ARGS=()

usage() {
  cat <<'EOF'
R.A.I.N. Lab local installer (macOS/Linux)

Usage:
  ./install.sh [options]

This installer mirrors the Windows INSTALL_RAIN.cmd flow:
1. install uv (via curl) if missing
2. create .venv with Python 3.12
3. compile and sync pinned dependencies
4. run bootstrap_local.py to fetch the prebuilt runtime and initialize config
5. hand off to James with chat_with_james.py --greet

Options:
  --recreate-venv          Remove .venv before recreating it
  --skip-preflight         Pass through to bootstrap_local.py
  --skip-binary-fetch      Pass through to bootstrap_local.py
  --skip-config-init       Pass through to bootstrap_local.py
  --skip-env-setup         Pass through to bootstrap_local.py
  --non-interactive        Pass through to bootstrap_local.py
  --release-repo <slug>    Pass through to bootstrap_local.py
  --release-tag <tag>      Pass through to bootstrap_local.py
  --bin-dir <path>         Pass through to bootstrap_local.py
  --register-rust-agents   Pass through to bootstrap_local.py
  --rust-api-url <url>     Pass through to bootstrap_local.py
  --registry-output <path> Pass through to bootstrap_local.py
  --no-greet               Skip the post-install James handoff
  -h, --help               Show this help

Notes:
  - On Windows, use INSTALL_RAIN.cmd instead.
  - Legacy source-build flags such as --docker or --install-rust are no longer
    supported by this front-door installer. Use the advanced docs if you need
    container or source-build workflows.
EOF
}

fail() {
  echo "[install] error: $*" >&2
  exit 1
}

info() {
  echo "[install] $*"
}

require_value() {
  local flag="$1"
  local value="${2:-}"
  if [[ -z "$value" ]]; then
    fail "$flag requires a value"
  fi
}

resolve_uv_path() {
  if command -v uv >/dev/null 2>&1; then
    command -v uv
    return 0
  fi

  if [[ -x "$HOME/.local/bin/uv" ]]; then
    printf '%s\n' "$HOME/.local/bin/uv"
    return 0
  fi

  return 1
}

install_uv() {
  local installer_path

  if ! command -v curl >/dev/null 2>&1; then
    fail "curl is required to install uv"
  fi

  installer_path="$(mktemp -t rain-install-uv.XXXXXX.sh)"

  info "Downloading uv installer"
  curl -LsSf "https://astral.sh/uv/install.sh" -o "$installer_path"
  sh "$installer_path"
  rm -f "$installer_path"
  export PATH="$HOME/.local/bin:$PATH"
}

ensure_uv() {
  local uv_path
  if uv_path="$(resolve_uv_path)"; then
    printf '%s\n' "$uv_path"
    return 0
  fi

  install_uv

  if uv_path="$(resolve_uv_path)"; then
    printf '%s\n' "$uv_path"
    return 0
  fi

  fail "uv installation completed but the uv executable was not found"
}

run_uv() {
  local uv_path="$1"
  shift
  info "$uv_path $*"
  "$uv_path" "$@"
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --recreate-venv)
        RECREATE_VENV=true
        shift
        ;;
      --skip-preflight|--skip-binary-fetch|--skip-config-init|--skip-env-setup|--non-interactive|--register-rust-agents)
        BOOTSTRAP_ARGS+=("$1")
        shift
        ;;
      --release-repo|--release-tag|--bin-dir|--rust-api-url|--registry-output)
        require_value "$1" "${2:-}"
        BOOTSTRAP_ARGS+=("$1" "$2")
        shift 2
        ;;
      --no-greet)
        SKIP_GREET=true
        shift
        ;;
      --docker|--guided|--no-guided|--install-system-deps|--install-rust|--prefer-prebuilt|--prebuilt-only|--force-source-build|--api-key|--provider|--model|--skip-onboard|--skip-build|--skip-install|--build-first)
        fail "legacy flag '$1' is not supported by the fetch-first installer; use the advanced docs or bootstrap_local.py directly"
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        fail "unknown option: $1"
        ;;
    esac
  done
}

main() {
  local system_name uv_path venv_dir venv_python

  system_name="$(uname -s)"
  case "$system_name" in
    Linux|Darwin) ;;
    *)
      fail "install.sh supports macOS/Linux only. On Windows, use INSTALL_RAIN.cmd"
      ;;
  esac

  parse_args "$@"

  if [[ ! -f "$REPO_ROOT/bootstrap_local.py" || ! -f "$REPO_ROOT/chat_with_james.py" ]]; then
    fail "run this installer from the repository root"
  fi

  if [[ ! -t 0 || ! -t 1 ]]; then
    SKIP_GREET=true
  fi

  uv_path="$(ensure_uv)"
  venv_dir="$REPO_ROOT/.venv"
  venv_python="$venv_dir/bin/python"

  if [[ "$RECREATE_VENV" == true && -d "$venv_dir" ]]; then
    info "Removing existing virtual environment"
    rm -rf "$venv_dir"
  fi

  run_uv "$uv_path" python install "$PYTHON_VERSION"
  run_uv "$uv_path" venv "$venv_dir" --python "$PYTHON_VERSION"
  local pip_lock_file="$REPO_ROOT/.uv-pip.lock"
  rm -f "$pip_lock_file"
  run_uv "$uv_path" pip compile "$REPO_ROOT/requirements-pinned.txt" -o "$pip_lock_file"
  run_uv "$uv_path" pip sync --python "$venv_python" "$pip_lock_file"
  run_uv "$uv_path" run --python "$venv_python" "$REPO_ROOT/bootstrap_local.py" "${BOOTSTRAP_ARGS[@]}"

  if [[ "$SKIP_GREET" == false ]]; then
    info "Handing off to James"
    run_uv "$uv_path" run --python "$venv_python" "$REPO_ROOT/chat_with_james.py" --greet
  else
    info "Setup complete. Next: uv run --python \"$venv_python\" rain_lab.py"
  fi
}

main "$@"
