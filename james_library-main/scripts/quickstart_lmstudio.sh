#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[1/4] Checking Python..."
if ! command -v python >/dev/null 2>&1; then
  echo "ERROR: python was not found on PATH."
  exit 1
fi

echo "[2/4] Bootstrapping local environment (.venv, dependencies, embedded ZeroClaw when available)..."
python bootstrap_local.py --skip-preflight

# shellcheck disable=SC1091
source .venv/bin/activate

echo "[3/4] Setting LM Studio defaults for this shell..."
export LM_STUDIO_BASE_URL="${LM_STUDIO_BASE_URL:-http://127.0.0.1:1234/v1}"
export LM_STUDIO_MODEL="${LM_STUDIO_MODEL:-qwen2.5-7b-instruct}"

echo "[4/4] Running health snapshot..."
python rain_lab.py --mode health || true

cat <<'EOF'

Quickstart complete.

Canonical next steps:
1) Start LM Studio and load a model.
2) Validate the full stack:
   python rain_lab.py --mode validate
3) Run guided first-run:
   python rain_lab.py --mode first-run
4) Optional: validate embedded ZeroClaw runtime directly:
   python rain_lab.py --mode status
   python rain_lab.py --mode models
5) Start chat:
   python rain_lab.py --mode chat --ui auto --topic "hello from LM Studio"

EOF
