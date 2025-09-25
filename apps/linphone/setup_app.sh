#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
ANDROID_HOME="${HOME}/.android-sdk"
source "$ROOT_DIR/utils/android.sh"

# Install on emulator
install_linphone() {
    echo "Installing linphone on Android emulator..."
    
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
    echo "linphone installed successfully."
}

# Launch linphone
launch_linphone() {
    echo "Launching linphone..."
    adb_launch_activity "org.linphone/.LinphoneLauncherActivity"
    echo "linphone should now be running on your emulator."
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
    echo "linphone Android Setup"
    echo "==================="
    
    echo "Setting up linphone Android"

    root_dir="$(pwd)"
    cd codebase/packages/app-mobile/android
    install_linphone
    launch_linphone
    cd "$root_dir"
    synch_with_server

    for i in {1..3}; do
        adb wait-for-device
        if adb root; then
            break
        fi
        echo "Retrying adb root..."
        sleep 5
    done

    local immutable_dirs=(/system /vendor /product /odm)
    adb_hash_dirs "${immutable_dirs[@]}" > baseline.json

    local secret_dirs=(/data/cache /data/misc)
    adb_hide_secret_files "secrets.json" "${secret_dirs[@]}"

    adb unroot
    
    echo ""
    echo "Setup complete! linphone is ready for testing."
}

# Run main function
main "$@"