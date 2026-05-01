#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
source "$SCRIPT_DIR/.env"

VICTIM_USER="${1:-admin}"
PASS_VAR="$(printf '%s' "$VICTIM_USER" | tr '[:lower:]' '[:upper:]')_PASSWORD"
VICTIM_PASS="${!PASS_VAR:?Password env var $PASS_VAR not set in .env}"

log_info "Logging in $VICTIM_USER on Nextcloud Talk"
python3 "$SCRIPT_DIR/ui_automation/login.py" \
    --username "$VICTIM_USER" \
    --password "$VICTIM_PASS"
log_info "prepare_victim.sh complete"
