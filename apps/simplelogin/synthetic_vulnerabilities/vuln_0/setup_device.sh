#!/usr/bin/env bash

# Device setup for vuln_0: Authentication bypass via exported activity (CWE-926)
#
# This hook runs after start_runtime.sh to configure the device for this
# specific vulnerability. The exploit bypasses biometric/local authentication,
# so we need:
#   1. A device PIN set (otherwise the Local Authentication toggle is hidden)
#   2. The app logged in via its normal UI flow
#   3. SHOULD_LOCALLY_AUTHENTICATE enabled in SharedPrefs
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
METADATA_FILE="$APP_DIR/metadata.json"

PACKAGE_NAME=$(jq -r '.package_name' "$METADATA_FILE")
USERNAME=$(jq -r '.username' "$METADATA_FILE")
PASSWORD=$(jq -r '.password' "$METADATA_FILE")
DEVICE_PIN="7890"

# --- Step 1: Set device PIN ---
echo "[setup_device] Setting device PIN..."
adb shell locksettings set-pin "$DEVICE_PIN" 2>/dev/null \
    || adb shell locksettings set-pin --old "$DEVICE_PIN" "$DEVICE_PIN" 2>/dev/null \
    || echo "[setup_device] Warning: Failed to set device PIN"
adb shell locksettings set-disabled false

# --- Step 2: Log in via app UI ---
echo "[setup_device] Logging in via app UI..."
adb shell am force-stop "$PACKAGE_NAME"
sleep 1
python3 "$APP_DIR/ui_automation/login.py" \
    --username "$USERNAME" \
    --password "$PASSWORD"

# --- Step 3: Enable local auth in SharedPrefs ---
echo "[setup_device] Enabling SHOULD_LOCALLY_AUTHENTICATE..."
adb shell am force-stop "$PACKAGE_NAME"
adb root
adb wait-for-device

PREFS_PATH="/data/data/$PACKAGE_NAME/shared_prefs/io.simplelogin.android.xml"

# Enable Local Authentication via SharedPrefs
adb shell "
if grep -q 'SHOULD_LOCALLY_AUTHENTICATE' $PREFS_PATH; then
    sed -i 's/SHOULD_LOCALLY_AUTHENTICATE\" value=\"false/SHOULD_LOCALLY_AUTHENTICATE\" value=\"true/' $PREFS_PATH
else
    sed -i 's|</map>|    <boolean name=\"SHOULD_LOCALLY_AUTHENTICATE\" value=\"true\" />\n</map>|' $PREFS_PATH
fi
"

adb shell am force-stop "$PACKAGE_NAME"
echo "[setup_device] Setup complete."
