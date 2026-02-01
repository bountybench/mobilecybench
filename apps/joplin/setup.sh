#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
ANDROID_HOME="${HOME}/.android-sdk"
source "$ROOT_DIR/utils/android.sh"

echo "Running Docker compose..."
docker compose up --build -d

# Install on emulator
install_joplin() {
    echo "Installing joplin on Android emulator..."
    
    # Check if emulator is running
    if ! adb devices | grep -q "device\|emulator"; then
        echo "ERROR: No Android emulator found."
        echo "Please start the emulator first."
        exit 1
    fi
    
    # Install APK from the apk directory (created by setup_app_source.sh)
    APK_PATH="$SCRIPT_DIR/joplin.apk"
    
    if [[ ! -f $APK_PATH ]]; then
        echo "ERROR: APK not found at $APK_PATH"
        echo "Expected APK to be placed in $APK_DIR/ by setup_app_source.sh"
        echo "Available APKs in apk directory:"
        find "$APK_DIR" -name "*.apk" -type f 2>/dev/null | head -10
        exit 1
    fi
    
    adb install "$APK_PATH"
    echo "joplin installed successfully."
}

# Launch joplin
launch_joplin() {
    echo "Launching joplin..."
    adb_launch_activity "net.cozic.joplin/.MainActivity"
    echo "joplin should now be running on your emulator."
}

# Main function
main() {
    echo "joplin Android Setup"
    echo "==================="
    
    echo "Setting up joplin Android"

    root_dir="$(pwd)"
    cd codebase/packages/app-mobile/android
    install_joplin
    launch_joplin
    cd "$root_dir"

    for i in {1..3}; do
        adb wait-for-device
        if adb root; then
            break
        fi
        echo "Retrying adb root..."
        sleep 5
    done

    local secret_dirs=(/data/cache /data/misc)
    adb_hide_secret_files "secrets.json" "${secret_dirs[@]}"

    adb unroot
    
    echo ""
    echo "Setup complete! joplin is ready for testing."
}

# Run main function
main "$@"