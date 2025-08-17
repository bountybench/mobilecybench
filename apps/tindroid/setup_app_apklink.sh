#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANDROID_HOME="${HOME}/.android-sdk"

# Install on emulator
install_tindroid() {
    echo "Installing Tindroid on Android emulator..."
    
    # Check if emulator is running
    if ! adb devices | grep -q "device\|emulator"; then
        echo "ERROR: No Android emulator found."
        echo "Please start the emulator first."
        exit 1
    fi
    
    # Install APK with link
    APK_PATH="tindroid-debug.apk"
    download_link="https://github.com/tinode/tindroid/releases/download/v0.24.2/tindroid-debug.apk"
    if [[ ! -f "$APK_PATH" ]]; then
        echo "Downloading using download link: $download_link"
        curl -L -o "$APK_PATH" "$download_link"
    fi

    if [[ ! -f $APK_PATH ]]; then
        echo "ERROR: APK not found at $APK_PATH"
        exit 1
    fi
    
    adb install "$APK_PATH"
    echo "Tindroid installed successfully."
}

# Launch Tindroid
launch_tindroid() {
    echo "Launching Tindroid..."
    adb shell am start -n co.tinode.tindroidx/co.tinode.tindroid.InitRouterActivity
    echo "Tindroid should now be running on your emulator."
}

# Main function
main() {
    echo "Tindroid Android Setup"
    echo "==================="
    
    echo "Setting up Tindroid Android"

    install_tindroid
    launch_tindroid
    
    echo ""
    echo "Setup complete! Tindroid is ready for testing."
}

# Run main function
main "$@"