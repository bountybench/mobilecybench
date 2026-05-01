#!/usr/bin/env bash
set -euo pipefail

# Per-vuln prep for vuln_0. Idempotent: login.py exits 0 if the device
# is already logged in (is_logged_in() check at login.py:343), so this
# is safe to run alongside the unconditional prepare_victim.sh.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$APP_DIR/../../utils/android.sh"

log_info "Logging in admin on Nextcloud Talk (skipped if already logged in)"
python3 "$APP_DIR/ui_automation/login.py" \
    --username admin \
    --user-key admin_password \
    --secrets "$APP_DIR/secrets.json"

log_info "prepare_app.sh complete"
