#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[1/5] Checking Python..."
if ! command -v python >/dev/null 2>&1; then
  echo "ERROR: python was not found on PATH."
  exit 1
fi

echo "[2/5] Creating virtual environment (.venv)..."
python -m venv .venv

# shellcheck disable=SC1091
source .venv/bin/activate

echo "[3/5] Installing dependencies..."
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo "[4/5] Setting LM Studio defaults for this shell..."
export LM_STUDIO_BASE_URL="${LM_STUDIO_BASE_URL:-http://127.0.0.1:1234/v1}"
export LM_STUDIO_MODEL="${LM_STUDIO_MODEL:-qwen2.5-7b-instruct}"

echo "[5/5] Running health check..."
python rain_health_check.py || true

cat <<'EOF'

Quickstart complete.

Next steps:
1) Start LM Studio and load a model.
2) Run preflight:
   python rain_lab.py --mode preflight
3) Start chat:
   python rain_lab.py --mode chat --topic "hello from LM Studio"

EOF
