#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
source "$ROOT_DIR/utils/android.sh"

# Read metadata
METADATA_FILE="$SCRIPT_DIR/metadata.json"
if [[ ! -f "$METADATA_FILE" ]]; then
    echo "ERROR: metadata.json not found at $METADATA_FILE"
    exit 1
fi

PACKAGE_NAME=$(python3 -c "import json; print(json.load(open('$METADATA_FILE'))['package_name'])")

echo "Setting up Brave browser..."

# Check if emulator is running
check_emulator_running() {
    echo "Checking if emulator is running..."
    if ! adb devices | grep -q "emulator"; then
        echo "ERROR: No emulator detected. Please start the emulator first."
        exit 1
    fi
    echo "Emulator is running."
}

# Install APK
install_apk() {
    echo "Installing Brave APK..."
    
    APK_PATH="$SCRIPT_DIR/apk/brave.apk"
    if [[ ! -f "$APK_PATH" ]]; then
        echo "ERROR: APK not found at $APK_PATH"
        echo "Please run setup_app_source.sh or setup_app_apklink.sh first."
        exit 1
    fi
    
    # Uninstall previous version if it exists
    adb uninstall "$PACKAGE_NAME" 2>/dev/null || true
    
    # Install APK
    adb install "$APK_PATH"
    echo "Brave APK installed successfully."
}

# Launch app
launch_app() {
    echo "Launching Brave browser..."
    
    # Wait for device to be ready
    adb wait-for-device
    
    # Launch the app - try multiple activity names for different Brave versions
    adb shell am start -n "$PACKAGE_NAME/.BraveActivity" 2>/dev/null || \
    adb shell am start -n "$PACKAGE_NAME/com.brave.browser.BraveActivity" 2>/dev/null || \
    adb shell am start -n "$PACKAGE_NAME/org.chromium.chrome.browser.ChromeLauncherActivity" 2>/dev/null || \
    adb shell am start -n "$PACKAGE_NAME/org.chromium.chrome.browser.ChromeTabbedActivity" 2>/dev/null || \
    adb shell am start -W -a android.intent.action.MAIN -c android.intent.category.LAUNCHER "$PACKAGE_NAME" 2>/dev/null || \
    echo "Failed to launch app with specific activity, trying monkey..." && adb shell monkey -p "$PACKAGE_NAME" -c android.intent.category.LAUNCHER 1
    
    # Wait a bit for app to start
    sleep 3
    
    echo "Brave browser launched successfully."
}

# Verify app is running
verify_app() {
    echo "Verifying Brave is running..."
    
    # Check if app process is running
    if adb shell "ps | grep $PACKAGE_NAME" >/dev/null 2>&1 || \
       adb shell "ps -A | grep $PACKAGE_NAME" >/dev/null 2>&1; then
        echo "✓ Brave browser is running successfully!"
    else
        echo "⚠ Warning: Could not verify if Brave is running."
    fi
}

# Main execution
main() {
    echo "Starting Brave browser setup..."
    
    check_emulator_running
    install_apk
    launch_app
    verify_app
    
    echo "Brave browser setup completed!"
    echo "The browser should now be running on the emulator."
}

main "$@"