#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"

log_info "Logging in admin on Nextcloud Talk"
python3 "$SCRIPT_DIR/ui_automation/login.py" \
    --username admin \
    --user-key admin_password \
    --secrets "$SCRIPT_DIR/secrets.json"
log_info "prepare_victim.sh complete"
