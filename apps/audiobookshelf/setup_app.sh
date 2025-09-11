#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
ANDROID_HOME="${HOME}/.android-sdk"
source "$ROOT_DIR/utils/android.sh"

# Install on emulator
install_audiobookshelf() {
    echo "Installing audiobookshelf on Android emulator..."
    
    # Check if emulator is running
    if ! adb devices | grep -q "device\|emulator"; then
        echo "ERROR: No Android emulator found."
        echo "Please start the emulator first."
        exit 1
    fi
    
    # Install universal APK with correct path
    APK_PATH="app/build/outputs/apk/release/app-release.apk"
    
    if [[ ! -f $APK_PATH ]]; then
        echo "ERROR: APK not found at $APK_PATH"
        echo "Available APKs:"
        find app/build/outputs -name "*.apk" -type f 2>/dev/null | head -10
        exit 1
    fi
    
    adb install "$APK_PATH"
    echo "audiobookshelf installed successfully."
}

# Launch audiobookshelf
launch_audiobookshelf() {
    echo "Launching audiobookshelf..."
    adb_launch_activity "com.audiobookshelf.app/.MainActivity"
    echo "audiobookshelf should now be running on your emulator."
}

# Synching with server
# synch_with_server() {
#     echo "Synching app with server..."
#     pip install uiautomator2
#     python synch_app.py --username usera@localhost --password userAPW123
#     echo "Should now be synched with server."
# }

# Main function
main() {
    echo "audiobookshelf Android Setup"
    echo "==================="
    
    echo "Setting up audiobookshelf Android"

    root_dir="$(pwd)"
    cd codebase/android
    install_audiobookshelf
    launch_audiobookshelf
    cd "$root_dir"
    # synch_with_server
    
    echo ""
    echo "Setup complete! audiobookshelf is ready for testing."
}

# Run main function
main "$@"