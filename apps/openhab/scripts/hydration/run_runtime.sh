#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Agent-visible runtime hydration only. Keep replay-only material such as
# token minting, victim login, Android secret prefs, and verifier manifests in
# run_all.sh / prepare_victim.sh.
steps=(
  "02_seed_items_and_sitemap.sh"
  "05_seed_integrations.sh"
)

run_step() {
  local step="$1"
  if ! "$SCRIPT_DIR/$step"; then
    printf '[FAIL] %s failed\n' "$step" >&2
    exit 1
  fi
  if ! "$SCRIPT_DIR/$step" --check; then
    printf '[FAIL] %s idempotency check failed\n' "$step" >&2
    exit 1
  fi
}

for step in "${steps[@]}"; do
  printf '[INFO] running runtime %s\n' "$step" >&2
  run_step "$step"
done

printf '[INFO] runtime hydration complete\n' >&2
