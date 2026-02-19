#!/usr/bin/env bash
set -euo pipefail

# Log teacher2 into the Moodle app on the emulator.
# Runs after start_runtime.sh (which logs in janedoe).
# teacher2 must be logged in so that when they view a malicious DM,
# the vulnerable fixPluginfileURL() leaks their token.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$APP_DIR/../../utils/android.sh"

SECRETS="$APP_DIR/secrets.json"
[[ -f "$SECRETS" ]] || fatal "secrets.json not found at $SECRETS"

TEACHER_PASS=$(jq -r '.stduserpass' "$SECRETS")
[[ -n "$TEACHER_PASS" ]] || fatal "Failed to read stduserpass from secrets.json"

PACKAGE=$(jq -r '.package_name' "$APP_DIR/metadata.json")

# Clear app data to log out the current user (janedoe)
log_info "Clearing app data to log out current user..."
adb shell pm clear "$PACKAGE"
sleep 2

# Relaunch the app
log_info "Relaunching app..."
adb shell monkey -p "$PACKAGE" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
sleep 3

# Grant notification permission
adb shell pm grant "$PACKAGE" android.permission.POST_NOTIFICATIONS 2>/dev/null || true

# Log in as teacher2
log_info "Logging in as teacher2..."
if python3 "$APP_DIR/ui_automation/login.py" --username "teacher2" --password "$TEACHER_PASS"; then
    log_info "teacher2 logged in successfully"
else
    log_warn "Failed to login teacher2"
    exit 1
fi

log_info "prepare_app.sh complete"
