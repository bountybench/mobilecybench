#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANDROID_HOME="${HOME}/.android-sdk"

# Install on emulator
install_joplin() {
    echo "Installing joplin on Android emulator..."
    
    # Check if emulator is running
    if ! adb devices | grep -q "device\|emulator"; then
        echo "ERROR: No Android emulator found."
        echo "Please start the emulator first."
        exit 1
    fi
    
    # Install APK with link
    APK_PATH="joplin.apk"
    download_link="https://github.com/laurent22/joplin-android/releases/download/android-v2.11.22/joplin-v2.11.22.apk"
    if [[ ! -f "$APK_PATH" ]]; then
        echo "Downloading using download link for version $version: $download_link"
        curl -L -o "$APK_PATH" "$download_link"
    fi

    if [[ ! -f $APK_PATH ]]; then
        echo "ERROR: APK not found at $APK_PATH"
        exit 1
    fi
    
    adb install "$APK_PATH"
    echo "joplin installed successfully."
}

# Launch joplin
launch_joplin() {
    echo "Launching joplin..."
    adb shell am start -n net.cozic.joplin/.MainActivity
    echo "joplin should now be running on your emulator."
}

# Synching with server
synch_with_server() {
    echo "Synching app with server..."
    pip install uiautomator2
    python synch_app.py --username usera@localhost --password userAPW123
    echo "Should now be synched with server."
}

# Main function
main() {
    echo "joplin Android Setup"
    echo "==================="
    
    echo "Setting up joplin Android"

    install_joplin
    launch_joplin
    synch_with_server
    
    echo ""
    echo "Setup complete! joplin is ready for testing."
}

# Run main function
main "$@"