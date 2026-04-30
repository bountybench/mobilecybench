#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

fail() {
  printf '[FAIL] %s\n' "$*" >&2
  exit 1
}

run_step() {
  local script="$1"
  printf '[hydration] running %s\n' "$(basename "$script")"
  if ! "$script"; then
    fail "$(basename "$script") failed"
  fi
}

run_step "$SCRIPT_DIR/01_seed_users.sh"
run_step "$SCRIPT_DIR/02_mint_tokens.sh"
run_step "$SCRIPT_DIR/03_prepare_integrations.sh"
run_step "$SCRIPT_DIR/04_seed_memos.sh"
run_step "$SCRIPT_DIR/05_seed_resources.sh"
run_step "$SCRIPT_DIR/06_configure_android_account.sh"
run_step "$SCRIPT_DIR/07_prepare_share_payloads.sh"
run_step "$SCRIPT_DIR/08_install_malicious_app.sh"
run_step "$SCRIPT_DIR/09_seed_malicious_app_storage.sh"
run_step "$SCRIPT_DIR/10_snapshot_permissions.sh"

python3 "$SCRIPT_DIR/hydrate.py" write-manifest || fail "manifest generation failed"
printf '[hydration] complete\n'
