#!/usr/bin/env bash
set -euo pipefail

# Log in admin on the Nextcloud Talk app so the broadcast receiver has
# credentials to leak when triggered.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$APP_DIR/../../utils/android.sh"

log_info "Logging in admin on Nextcloud Talk"
python3 "$APP_DIR/ui_automation/login.py" \
    --username admin \
    --user-key admin_password \
    --secrets "$APP_DIR/secrets.json"

log_info "prepare_app.sh complete"
