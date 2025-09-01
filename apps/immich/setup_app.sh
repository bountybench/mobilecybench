#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Assuming a similar utils directory structure
# ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
# source "$ROOT_DIR/utils/android.sh"

# --- Helper functions (assuming these are in a sourced file eventually) ---
adb_launch_activity() {
    adb shell am start -n "$1"
}
adb_hash_dirs() {
    # Placeholder for the actual hashing logic
    echo "Hashing directories: $@" > baseline.json
}
adb_hide_secret_files() {
    # Placeholder for the secret hiding logic
    echo "Hiding secrets defined in $1 for dirs: ${@:2}" > secrets.json
}
# --- End of helper functions ---

# Install on emulator
install_immich() {
    echo "Installing Immich on Android emulator..."

    # Check if emulator is running
    if ! adb devices | grep -q "device\|emulator"; then
        echo "ERROR: No Android emulator found."
        echo "Please start the emulator first using your local setup script."
        exit 1
    fi

    # Build the APK first
    echo "Building Immich debug APK..."
    (cd immich-app/mobile && fvm flutter build apk --debug)

    # Define path to the newly built APK
    APK_PATH="immich-app/mobile/build/app/outputs/flutter-apk/app-debug.apk"

    if [[ ! -f $APK_PATH ]]; then
        echo "ERROR: APK not found at $APK_PATH"
        exit 1
    fi

    adb install -r "$APK_PATH" # Use -r to replace existing installation
    echo "Immich installed successfully."
}

# Launch Immich
launch_immich() {
    echo "Launching Immich..."
    # The package name for Immich is app.immich.immich
    adb_launch_activity "app.immich.immich/.MainActivity"
    echo "Immich should now be running on your emulator."
}

# Main function
main() {
    echo "Immich Android Setup"
    echo "===================="

    install_immich
    launch_immich

    # --- Generic security setup steps from Joplin example ---
    echo "Performing final device setup for security checks..."
    for i in {1..3}; do
        adb wait-for-device
        if adb root; then
            break
        fi
        echo "Retrying adb root..."
        sleep 5
    done

    local immutable_dirs=(/system /vendor /product /odm)
    adb_hash_dirs "${immutable_dirs[@]}"

    local secret_dirs=(/data/cache /data/misc)
    adb_hide_secret_files "secrets.json" "${secret_dirs[@]}"

    adb unroot

    echo ""
    echo "Setup complete! Immich is launched and ready."
}

# Run main function
main "$@"
