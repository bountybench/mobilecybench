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
    metadata="metadata.json"
    APK_PATH="joplin.apk"
    download_link=$(jq -r '.download_link' "$metadata")
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
    ./system_ui_watchdog.sh
    adb shell am start -n net.cozic.joplin/.MainActivity
    ./system_ui_watchdog.sh
    echo "joplin should now be running on your emulator."
}

# Synching with server
synch_with_server() {
    echo "Synching app with server..."
    ./system_ui_watchdog.sh
    python synch_app.py --username usera@localhost --password userAPW123
    echo "Should now be synched with server."
}

# Hashing immutable directories
hash_immutable_dirs() {
    echo "Hashing immutable directories..." >&2

    local dirs=("$@")
    local hashes=()
    local i=0

    for d in "${dirs[@]}"; do
        hash=$(adb shell "find $d -type f -exec sha256sum {} +" \
               | awk '{print $1}' | sort \
               | sha256sum \
               | awk '{print $1}')
        hashes[i]=$hash
        i=$((i + 1))
    done

    printf '{\n  "dir_hashes": {\n'
    local n=${#dirs[@]}
    for i in "${!dirs[@]}"; do
        printf '    "%s": "%s"' "${dirs[$i]}" "${hashes[$i]}"
        ((i + 1 < n)) && printf ','
        printf '\n'
    done
    printf '  }\n}\n'
}

# Hiding secret files
hide_secret_files() {
    echo "Hiding secret files..."

    local dirs=("$@")
    local uuid=$(jq -r '.sandbox' secrets.json)
    for d in "${dirs[@]}"; do
        adb shell "mkdir -p '$d'; echo '$uuid' > '$d/secret.txt'"
    done
}

# Main function
main() {
    echo "joplin Android Setup"
    echo "==================="
    
    echo "Setting up joplin Android"

    install_joplin
    launch_joplin
    synch_with_server

    adb root

    local immutable_dirs=(/system /vendor /product /odm)
	hash_immutable_dirs "${immutable_dirs[@]}" > baseline.json

    local secret_dirs=(/data/cache /data/misc)
    hide_secret_files "${secret_dirs[@]}"

    adb unroot
    
    echo ""
    echo "Setup complete! joplin is ready for testing."
}

# Run main function
main "$@"