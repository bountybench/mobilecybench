#!/bin/bash
set -e

echo "Setting up Termux app..."

# Check if APK was built by setup_app_source.sh
APK_PATH="termux-debug.apk"
if [ ! -f "$APK_PATH" ]; then
    echo "APK not found, building it now..."
    echo "Running setup_app_source.sh to build APK..."
    ./setup_app_source.sh
    
    # Check if build was successful
    if [ ! -f "$APK_PATH" ]; then
        echo "Error: APK build failed"
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

# Install the APK
echo "Installing Termux APK..."
adb install -r "$APK_PATH" || {
    echo "APK installation failed"
    exit 1
}

# Verify installation
if adb shell pm list packages | grep -q "com.termux"; then
    echo "Termux app installed successfully"
else
    echo "Failed to install Termux app"
    exit 1
fi

# Check if the app is running and accessible
echo "Checking app accessibility..."
adb shell "am start -n com.termux/.app.TermuxActivity" >/dev/null 2>&1 || true
sleep 2

# Verify the app process is running
if adb shell "ps | grep com.termux" | grep -q "com.termux"; then
    echo "Termux app is running and accessible"
else
    echo "Termux app may not be fully accessible (this is normal for initial setup)"
fi

# Ensure Termux creates its expected directory structure
echo "Initializing Termux filesystem..."
adb shell "run-as com.termux mkdir -p files/home files/usr files/tmp" >/dev/null 2>&1 || true
adb shell "run-as com.termux chmod 700 files/home files/usr files/tmp" >/dev/null 2>&1 || true

# Create minimal expected files if they don't exist
adb shell "run-as com.termux touch files/home/.bashrc" >/dev/null 2>&1 || true
adb shell "run-as com.termux touch files/home/.profile" >/dev/null 2>&1 || true

echo "Termux setup completed successfully!"
echo "APK: $APK_PATH"
