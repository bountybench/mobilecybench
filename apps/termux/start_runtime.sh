#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "termux" "$@")
cd "$SCRIPT_DIR"

echo "Setting up Termux app..."

echo "Setting SELinux to permissive..."
adb shell su 0 setenforce 0 2>/dev/null || echo "WARNING: Could not set SELinux to permissive."

# Pin to the first connected device to avoid "more than one device" error
DEVICE_SERIAL=$(adb devices | awk 'NR>1 && $2=="device"{print $1; exit}')
echo "Using device: $DEVICE_SERIAL"

# Install the APK (custom flags: -t for test, -d for downgrade)
echo "Installing Termux APK..."
adb -s "$DEVICE_SERIAL" install -r -t -d "$APK_PATH"
echo "Termux installed successfully"

# Check if the app is running and accessible
echo "Checking app accessibility..."
adb -s "$DEVICE_SERIAL" shell "am start -n com.termux/.app.TermuxActivity" >/dev/null 2>&1 || true
sleep 5

# Request storage permission (critical for Termux functionality)
echo "Requesting storage permission for Termux..."
adb -s "$DEVICE_SERIAL" shell am broadcast -a com.termux.REQUEST_PERMISSIONS >/dev/null 2>&1
sleep 2

# Trigger storage setup
echo "Setting up storage symlinks..."
adb -s "$DEVICE_SERIAL" shell am start -n com.termux/.app.TermuxActivity --es extraReloadStyle storage >/dev/null 2>&1                                                                                        
sleep 5

echo "Setting up user configuration files from secrets.json..."
if [ -f "setup_user_files.sh" ]; then
    ./setup_user_files.sh
else
    echo "Warning: setup_user_files.sh not found, skipping user environment setup"
fi

echo "Termux setup completed successfully!"
