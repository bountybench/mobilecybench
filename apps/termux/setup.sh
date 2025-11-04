#!/bin/bash
set -e

echo "Setting up Termux app..."

APK_PATH="apk/termux.apk"
if [ ! -f "$APK_PATH" ]; then
    echo "APK not found, building it now..."
    echo "Running setup_app_source.sh to build APK..."
    if ! ./setup_app_source.sh; then
        echo "Error: setup_app_source.sh failed"
        exit 1
    fi
    
    # Check if build was successful - wait a moment for file system sync
    sleep 1
    if [ ! -f "$APK_PATH" ]; then
        echo "Error: APK build failed - APK not found at $APK_PATH"
        echo "Available APK files:"
        ls -la apk/ 2>/dev/null || echo "apk/ directory not found"
        exit 1
    fi
    echo "APK built successfully"
fi

echo "APK found: $APK_PATH"
echo "APK size: $(du -h "$APK_PATH" | cut -f1)"

# Check if device is available
if ! command -v adb >/dev/null 2>&1; then
    echo "Error: adb not found in PATH"
    exit 1
fi

adb start-server >/dev/null || true

if ! adb devices | grep -q "device"; then
    echo "Error: No Android device/emulator detected"
    echo "Please start the emulator first"
    exit 1
fi

# Pin to the first connected device to avoid "more than one device" error
DEVICE_SERIAL=$(adb devices | awk 'NR>1 && $2=="device"{print $1; exit}')
echo "Using device: $DEVICE_SERIAL"

# Install the APK
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
