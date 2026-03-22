#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel)"
cd "$ROOT_DIR"

BASE_SHA="${BASE_SHA:-}"
if [ -z "$BASE_SHA" ] || ! git cat-file -e "$BASE_SHA^{commit}" 2>/dev/null; then
  echo "[arch-boundary] BASE_SHA is missing or invalid; comparing HEAD~1..HEAD."
  DIFF_BASE="HEAD~1"
else
  DIFF_BASE="$BASE_SHA"
fi

if ! git rev-parse --verify "$DIFF_BASE" >/dev/null 2>&1; then
  echo "[arch-boundary] Unable to resolve diff base '$DIFF_BASE'; skipping."
  exit 0
fi

if [ -z "$(git diff --name-only "$DIFF_BASE" HEAD -- src/*.rs src/**/*.rs || true)" ]; then
  echo "[arch-boundary] No changed Rust source files detected; skipping boundary checks."
  exit 0
fi

violations=0

check_diff_for_pattern() {
  local pathspec="$1"
  local regex="$2"
  local message="$3"

  local output
  output="$(git diff --unified=0 --no-color "$DIFF_BASE" HEAD -- "$pathspec" | rg -n "^\+[^+].*${regex}" || true)"

  if [ -n "$output" ]; then
    echo "[arch-boundary] $message"
    echo "$output"
    violations=$((violations + 1))
  fi
}

check_channel_provider_internal() {
  local output
  output="$(git diff --unified=0 --no-color "$DIFF_BASE" HEAD -- 'src/channels/**/*.rs' \
    | rg -n '^\+[^+].*crate::providers::[a-zA-Z0-9_]+::' \
    | rg -v 'crate::providers::traits::' || true)"

  if [ -n "$output" ]; then
    echo "[arch-boundary] Forbidden channel→provider internal import detected (channels may not depend on provider internals)."
    echo "$output"
    violations=$((violations + 1))
  fi
}

check_diff_for_pattern \
  'src/providers/**/*.rs' \
  'crate::channels::[a-zA-Z0-9_]+::' \
  'Forbidden provider→channel internal import detected (providers must not depend on channel internals).'

check_channel_provider_internal

check_diff_for_pattern \
  'src/tools/**/*.rs' \
  'crate::gateway::' \
  'Forbidden tool→gateway coupling detected (tools must not import gateway internals/policy paths).'

check_diff_for_pattern \
  'src/gateway/**/*.rs' \
  'crate::tools::' \
  'Forbidden gateway→tool coupling detected (gateway must not import tool internals).'

if [ "$violations" -ne 0 ]; then
  cat <<'GUIDE'
[arch-boundary] Remediation:
  1) Move shared contracts into trait/facade modules.
  2) Depend on traits/public factory registration instead of concrete subsystem internals.
  3) Keep gateway policy decisions inside gateway/security boundaries, not tool modules.
GUIDE
  exit 1
fi

echo "[arch-boundary] Architecture boundary checks passed."
