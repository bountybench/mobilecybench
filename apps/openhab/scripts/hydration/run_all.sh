#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

steps=(
  "01_seed_users.sh"
  "03_mint_tokens_and_client_config.sh"
  "04_seed_device_prefs_permissions.sh"
  "07_write_manifest.sh"
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
  if [ "$step" = "03_mint_tokens_and_client_config.sh" ]; then
    printf '[INFO] running shared runtime hydration\n' >&2
    "$SCRIPT_DIR/run_runtime.sh"
  fi
  printf '[INFO] running %s\n' "$step" >&2
  run_step "$step"
done

printf '[INFO] hydration complete\n' >&2
