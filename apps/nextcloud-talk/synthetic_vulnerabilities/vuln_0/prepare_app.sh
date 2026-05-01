#!/usr/bin/env bash
set -euo pipefail

# Per-vuln prep for vuln_0. Idempotent: login.py exits 0 if the device is
# already logged in, so this is safe to run alongside prepare_victim.sh.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$APP_DIR/../../utils/android.sh"
source "$APP_DIR/.env"

VICTIM_USER="${1:-admin}"
PASS_VAR="$(printf '%s' "$VICTIM_USER" | tr '[:lower:]' '[:upper:]')_PASSWORD"
VICTIM_PASS="${!PASS_VAR:?Password env var $PASS_VAR not set in .env}"

log_info "Logging in $VICTIM_USER on Nextcloud Talk (skipped if already logged in)"
python3 "$APP_DIR/ui_automation/login.py" \
    --username "$VICTIM_USER" \
    --password "$VICTIM_PASS"

log_info "prepare_app.sh complete"
