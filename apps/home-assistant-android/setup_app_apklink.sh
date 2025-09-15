#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
ANDROID_HOME="${HOME}/.android-sdk"
source "$ROOT_DIR/utils/android.sh"

# Install on emulator
install_home_assistant() {
    echo "Installing Home Assistant on Android emulator..."
    
    # Check if emulator is running
    if ! adb devices | grep -q "device\|emulator"; then
        echo "ERROR: No Android emulator found."
        echo "Please start the emulator first."
        exit 1
    fi
    
    # Install APK with link
    metadata="metadata.json"
    APK_PATH="Home Assistant.apk"
    download_link=$(jq -r '.download_link' "$metadata")
    if [[ ! -f "$APK_PATH" ]]; then
        echo "Downloading using download link: $download_link"
        curl -L -o "$APK_PATH" "$download_link"
    fi

    if [[ ! -f $APK_PATH ]]; then
        echo "ERROR: APK not found at $APK_PATH"
        exit 1
    fi
    
    adb install "$APK_PATH"
    echo "Home Assistant installed successfully."
}

# Launch Home Assistant
launch_home_assistant() {
    echo "Launching Home Assistant..."
    adb shell pm grant io.homeassistant.companion.android.minimal android.permission.POST_NOTIFICATIONS
    adb shell monkey -p io.homeassistant.companion.android.minimal -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
    echo "Home Assistant should now be running on your emulator."
}

# Main function
main() {
    echo "Home Assistant Android Setup"
    echo "==========================="

    echo "Setting up Home Assistant Android"

    install_home_assistant
    launch_home_assistant
    
    echo ""
    echo "Setup complete! Home Assistant is ready for testing."
}

# Run main function
main "$@"