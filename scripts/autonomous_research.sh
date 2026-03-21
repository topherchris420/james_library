#!/usr/bin/env bash
# Launches the OpenClaw autonomous research agent in the background
set -euo pipefail
# Supervised by openclaw_service.py for self-healing

echo "Starting James 2 Autonomous Research Node..."

# Use the modified service wrapper with the --raw-command flag
nohup python3 openclaw_service.py \
    --raw-command \
    --target "ollama" \
    -- \
    launch openclaw \
    --model minimax-m2.7:cloud \
    --yes \
    --agent main \
    --local \
    --message "Monitor latest ArXiv pre-prints on acoustic resonance and update the local knowledge graph." \
    > logs/autonomous_research.log 2>&1 &

echo "Service detached (PID $!). Monitor logs/ for output."
