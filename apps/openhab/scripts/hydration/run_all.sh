#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

steps=(
  "01_seed_users.sh"
  "02_seed_items_and_sitemap.sh"
  "03_mint_tokens_and_client_config.sh"
  "04_seed_device_prefs_permissions.sh"
  "05_seed_integrations.sh"
  "06_seed_malicious_app_substrate.sh"
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
  printf '[INFO] running %s\n' "$step" >&2
  run_step "$step"
done

printf '[INFO] hydration complete\n' >&2
