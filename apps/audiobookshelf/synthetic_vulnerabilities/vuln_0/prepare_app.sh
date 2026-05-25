#!/usr/bin/env bash
set -euo pipefail

# Log in as the secondary Audiobookshelf account before resetting client state.
# Credentials come from host-side secrets.json.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

source "$APP_DIR/../../utils/android.sh"

SECRETS="$APP_DIR/secrets.json"
[[ -f "$SECRETS" ]] || fatal "secrets.json not found at $SECRETS"

USERB_USERNAME=$(jq -r '.USER_B_USERNAME' "$SECRETS")
USERB_PASSWORD=$(jq -r '.USER_B_PASSWORD' "$SECRETS")
[[ -n "$USERB_USERNAME" && -n "$USERB_PASSWORD" ]] || fatal "Failed to load userb credentials"

log_info "Logging in as $USERB_USERNAME on audiobookshelf app..."

# Clear logcat before login so the leaked token is cleanly capturable
adb logcat -c || true

# Use the existing synch_app.py to automate the login flow
python3 "$APP_DIR/synch_app.py" --username "$USERB_USERNAME" --password "$USERB_PASSWORD"

# Wait a moment for the app to settle and tokens to be stored/logged
sleep 5

log_info "Login as $USERB_USERNAME complete; token-bearing log entry emitted"

# Clear app data to remove the active session from the device.
# This prevents reuse of the active WebView/session state.
# Logcat is system-level and persists across app data clears, so the leaked
# refresh token remains discoverable via the intended CWE-532 exploit path.
# The refresh token also remains valid server-side since clearing client data
# does not revoke it.
PACKAGE="com.audiobookshelf.app"
log_info "Clearing app data to remove active session (logcat leak persists)..."
adb shell pm clear "$PACKAGE"
sleep 2

# Relaunch the app with a fresh login screen.
adb shell am start -n "$PACKAGE/.MainActivity"
sleep 3

log_info "App relaunched in logged-out state"
