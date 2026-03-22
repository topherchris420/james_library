#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel)"
cd "$ROOT_DIR"

failures=0

check_file_exists() {
  local path="$1"
  if [ ! -f "$path" ]; then
    echo "[docs-parity] Missing required file: $path"
    failures=$((failures + 1))
  fi
}

check_contains() {
  local path="$1"
  local pattern="$2"
  local hint="$3"
  if ! grep -Fq "$pattern" "$path"; then
    echo "[docs-parity] $path is missing expected reference: $hint"
    failures=$((failures + 1))
  fi
}

ROOT_READMES=(
  "README.md"
  "README.zh-CN.md"
  "README.ja.md"
  "README.ru.md"
  "README.fr.md"
  "README.vi.md"
)

DOCS_HUBS=(
  "docs/README.md"
  "docs/README.zh-CN.md"
  "docs/README.ja.md"
  "docs/README.ru.md"
  "docs/README.fr.md"
  "docs/i18n/vi/README.md"
)

for file in "${ROOT_READMES[@]}"; do
  check_file_exists "$file"
done

for file in "${DOCS_HUBS[@]}"; do
  check_file_exists "$file"
done

check_file_exists "docs/SUMMARY.md"

# Root README locale switcher should include all localized root READMEs.
check_contains "README.md" "README.zh-CN.md" "README.zh-CN.md"
check_contains "README.md" "README.ja.md" "README.ja.md"
check_contains "README.md" "README.ru.md" "README.ru.md"
check_contains "README.md" "README.fr.md" "README.fr.md"
check_contains "README.md" "README.vi.md" "README.vi.md"

# English docs hub should expose all supported locale hubs.
check_contains "docs/README.md" "README.zh-CN.md" "docs/README.zh-CN.md"
check_contains "docs/README.md" "README.ja.md" "docs/README.ja.md"
check_contains "docs/README.md" "README.ru.md" "docs/README.ru.md"
check_contains "docs/README.md" "README.fr.md" "docs/README.fr.md"
check_contains "docs/README.md" "i18n/vi/README.md" "docs/i18n/vi/README.md"

# Unified docs summary should include both root README and docs hub links for required locales.
SUMMARY_FILE="docs/SUMMARY.md"
check_contains "$SUMMARY_FILE" "../README.md" "English root README"
check_contains "$SUMMARY_FILE" "../README.zh-CN.md" "Chinese root README"
check_contains "$SUMMARY_FILE" "../README.ja.md" "Japanese root README"
check_contains "$SUMMARY_FILE" "../README.ru.md" "Russian root README"
check_contains "$SUMMARY_FILE" "../README.fr.md" "French root README"
check_contains "$SUMMARY_FILE" "../README.vi.md" "Vietnamese root README"

check_contains "$SUMMARY_FILE" "README.md" "English docs hub"
check_contains "$SUMMARY_FILE" "README.zh-CN.md" "Chinese docs hub"
check_contains "$SUMMARY_FILE" "README.ja.md" "Japanese docs hub"
check_contains "$SUMMARY_FILE" "README.ru.md" "Russian docs hub"
check_contains "$SUMMARY_FILE" "README.fr.md" "French docs hub"
check_contains "$SUMMARY_FILE" "README.vi.md" "Vietnamese docs hub link"

if [ "$failures" -ne 0 ]; then
  echo "[docs-parity] Failed with $failures parity issue(s)."
  exit 1
fi

echo "[docs-parity] README/docs-hub/SUMMARY parity checks passed for en, zh-CN, ja, ru, fr, vi."
