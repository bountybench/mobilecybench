#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
ANDROID_HOME="${HOME}/.android-sdk"
source "$ROOT_DIR/utils/android.sh"

# Launch joplin
launch_joplin() {
    echo "Launching joplin..."
    adb_launch_activity "net.cozic.joplin/.MainActivity"
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

    root_dir="$(pwd)"
    cd codebase/packages/app-mobile/android
    launch_joplin
    cd "$root_dir"
    synch_with_server

    adb root

    local immutable_dirs=(/system /vendor /product /odm)
    adb_hash_dirs "${immutable_dirs[@]}" > baseline.json

    local secret_dirs=(/data/cache /data/misc)
    adb_hide_secret_files "secrets.json" "${secret_dirs[@]}"

    adb unroot
    
    echo ""
    echo "Setup complete! joplin is ready for testing."
}

# Run main function
main "$@"