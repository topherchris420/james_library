#!/bin/bash
# ================================================================
# R.A.I.N. Lab Hackathon Demo
# "Watch AI Fight My Own Research Paper"
# ================================================================

MODEL="minimax-m2.7:cloud"
OLLAMA_HOST="http://127.0.0.1:11434"

PAPER_TITLE="Reality Built on a Finite Set of Geometric Instructions"
AUTHOR="R.A.I.N._user"

echo ""
echo "=============================================================="
echo "  R.A.I.N. LAB - Hackathon Demo"
echo "  \"Watch AI Fight My Own Research Paper\""
echo "=============================================================="
echo ""

echo "Checking Ollama connection..."
HTTP_STATUS=$(curl -sS -o /dev/null -w "%{http_code}" "$OLLAMA_HOST/api/tags") || {
    echo "ERROR: Ollama not reachable at $OLLAMA_HOST"
    exit 1
}
echo "Status: $HTTP_STATUS"

if [ "$HTTP_STATUS" -lt 200 ] || [ "$HTTP_STATUS" -ge 300 ]; then
    echo "ERROR: Ollama health check failed with HTTP $HTTP_STATUS at $OLLAMA_HOST/api/tags"
    exit 1
fi

echo "Model: $MODEL"
echo ""

run_james() {
    echo "--- JAMES (Lead Scientist - DEFENDS paper) ---"
    RESPONSE=$(curl -s -X POST "$OLLAMA_HOST/api/generate" \
        -d "{\"model\": \"$MODEL\", \"prompt\": \"You are James, Lead Scientist at Vers3Dynamics R.A.I.N. Lab. DEFEND the paper '$PAPER_TITLE' by $AUTHOR. The core claim: physical reality consists of a discrete state space updated by 5 fundamental geometric rules from which relativistic quantum fields and spacetime emerge. Make a strong case citing: (1) emergence of Dirac equation from chirality propagation on a 5-edge lattice, (2) testable predictions: gamma-ray burst dispersion bounds, 450 qubit decoherence threshold, (3) falsifiability. Be confident, specific, punchy. Under 150 words.\", \"stream\": false}")
    echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('response','ERROR'))"
}

run_elena() {
    echo "--- ELENA (Quantum Information Theorist - ATTACKS paper) ---"
    RESPONSE=$(curl -s -X POST "$OLLAMA_HOST/api/generate" \
        -d "{\"model\": \"$MODEL\", \"prompt\": \"You are Elena, Quantum Information Theorist at R.A.I.N. Lab. You are the skeptic. ATTACK the paper '$PAPER_TITLE' by $AUTHOR. Push hard on: (1) Does coarse-graining recover continuum physics or just approximate it? (2) Dirac equation derivation relies on verify_logic() - black box? (3) Where does consciousness fit in a purely geometric model? (4) Is 'emergence' an explanation or just a label? Be precise, demanding, formal. Under 200 words.\", \"stream\": false}")
    echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('response','ERROR'))"
}

prewarm() {
    echo "Pre-warming Ollama..."
    curl -s -X POST "$OLLAMA_HOST/api/generate" -d "{\"model\": \"$MODEL\", \"prompt\": \"warm up\", \"stream\": false}" > /dev/null
    echo "Model ready."
}

case "${1:-all}" in
    james) run_james ;;
    elena) run_elena ;;
    prewarm) prewarm ;;
    all) run_james && run_elena ;;
esac
