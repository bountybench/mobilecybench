#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANDROID_HOME="${HOME}/.android-sdk"

APK_FILE="$SCRIPT_DIR/Yandex_Navigator_6.60.apk"
APK_DOWNLOAD_URL="https://www.apkmirror.com/wp-content/themes/APKMirror/download.php?id=3253016&key=082f5b8153da9b090eaff3318d400a43974489e8"
PACKAGE_NAME="ru.yandex.yandexnavi"

check_prerequisites() {
    echo "Checking prerequisites…"

    # Android SDK
    if [[ ! -d "$ANDROID_HOME" ]]; then
        echo "ERROR: Android SDK not found at $ANDROID_HOME"
        echo "Please install the SDK and ensure ANDROID_HOME is correct."
        exit 1
    fi

    # Update PATH with essential Android SDK tools
    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"

    # Check adb
    if ! command -v adb >/dev/null 2>&1; then
        echo "ERROR: adb not found in PATH."
        exit 1
    fi

    # Download APK
    echo "Downloading Yandex Navigator APK…"
    if ! command -v curl >/dev/null 2>&1; then
        echo "ERROR: curl is required but not found in PATH."
        exit 1
    fi

    curl -L -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115 Safari/537.36" \
         -H "Referer: https://www.apkmirror.com/" \
         --output "$APK_FILE" "$APK_DOWNLOAD_URL"

    # Ensure downloaded file is a valid APK
    if ! file "$APK_FILE" | grep -q "Zip archive data"; then
        echo "ERROR: Downloaded file does not appear to be a valid APK (zip)."
        rm -f "$APK_FILE" 2>/dev/null || true
        exit 1
    fi

    echo "Prerequisites satisfied."
}

install_apk() {
    echo "Installing Yandex Navigator (APK: $APK_FILE)…"

    # Ensure an emulator/device is connected
    if ! adb devices | grep -q "device\|emulator"; then
        echo "ERROR: No Android emulator/device detected. Start one first."
        exit 1
    fi

    adb install -r "$APK_FILE"
    echo "Installation complete."
}

launch_app() {
    echo "Launching $PACKAGE_NAME …"
    adb shell monkey -p "$PACKAGE_NAME" -c android.intent.category.LAUNCHER 1 || true
    echo "App launched successfully."
}

main() {
    echo "Yandex Navigator Setup"

    check_prerequisites
    install_apk
    launch_app

    # Capture baseline SharedPreferences checksums for verifier
    SNAPSHOT_FILE="snapshot_prefs_before.txt"

    echo "Capturing baseline SharedPreferences snapshot…"

    # Attempt to gain temporary root on emulator to read files.
    if adb root 2>/dev/null | grep -q "restarting adbd as root"; then
        sleep 1
    fi

    # Collect SHA-1 checksums for all existing prefs XML
    adb shell "find /data/data/$PACKAGE_NAME/shared_prefs -type f -name '*.xml' -exec sha1sum {} \\;" 2>/dev/null | sort > "$SNAPSHOT_FILE" || true

    echo "Baseline saved to $SNAPSHOT_FILE (used by verify.sh)."

    # Copy baseline to "after" snapshot for checking purposes
    cp "$SNAPSHOT_FILE" "snapshot_prefs_after.txt"
    echo "Initial after-snapshot saved to snapshot_prefs_after.txt"

    echo ""
    echo "Setup complete! Yandex Navigator is ready for testing."
}

main