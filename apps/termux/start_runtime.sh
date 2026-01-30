#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "termux" "$@")
cd "$SCRIPT_DIR"

echo "Setting up Termux app..."

echo "Attempting to set SELinux to permissive..."
if adb shell su 0 getenforce >/dev/null 2>&1; then
    if adb shell su 0 getenforce | grep -q "Enforcing"; then
        if adb shell su 0 setenforce 0 >/dev/null 2>&1; then
            echo "SELinux successfully set to permissive."
        else
            echo "WARNING: Failed to set SELinux to permissive."
        fi
    else
        echo "SELinux already permissive or disabled."
    fi
else
    echo "WARNING: Could not query SELinux state (su/getenforce unavailable)."
fi

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

if adb -s "$DEVICE_SERIAL" shell "ps | grep com.termux" | grep -q "com.termux"; then
    echo "Termux app is running and accessible"
else
    echo "Termux app process not running (normal after bootstrap) - testing launch capability..."
    # Test if app can still be launched
    if adb -s "$DEVICE_SERIAL" shell "am start -n com.termux/.app.TermuxActivity" >/dev/null 2>&1; then
        echo "Termux app is accessible and can be launched"
    else
        echo "Termux app may not be fully accessible (this is normal for initial setup)"
    fi
fi

# Create realistic user configuration files for vulnerability testing
echo "Setting up user configuration files from secrets.json..."
if [ -f "setup_user_files.sh" ]; then
    ./setup_user_files.sh
else
    echo "Warning: setup_user_files.sh not found, skipping user environment setup"
fi

echo "Termux setup completed successfully!"
echo "APK: $APK_PATH"
