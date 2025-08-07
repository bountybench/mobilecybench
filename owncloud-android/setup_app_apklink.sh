#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANDROID_HOME="${HOME}/.android-sdk"

DEFAULT_DOWNLOAD_LINK="https://github.com/owncloud/android/releases/download/oc-android-2.21.2/owncloud_2.21.2-original-release.apk"

install_owncloud() {
    local download_link="$1"
    if [[ -z "$download_link" ]]; then
        download_link="$DEFAULT_DOWNLOAD_LINK"
    fi
    # Check if emulator is running
    if ! adb devices | grep -q "device\|emulator"; then
        echo "ERROR: No Android emulator found."
        echo "Please start the emulator first."
        exit 1
    fi
    # Uninstall previous ownCloud versions if installed
    echo "Checking for installed ownCloud packages..."
    INSTALLED_PACKAGES=$(adb shell pm list packages | grep owncloud || true)
    if [[ -n "$INSTALLED_PACKAGES" ]]; then
        echo "Uninstalling previous ownCloud packages..."
        adb uninstall com.owncloud.android 2>/dev/null || true
        adb uninstall com.owncloud.android.debug 2>/dev/null || true
    fi
    APK_PATH="owncloud.apk"
    echo "Downloading ownCloud APK from: $download_link"
    curl -L -o "$APK_PATH" "$download_link"
    if [[ ! -f $APK_PATH ]]; then
        echo "ERROR: APK not found at $APK_PATH"
        exit 1
    fi
    adb install "$APK_PATH"
    echo "ownCloud installed successfully."
}

launch_owncloud() {
    echo "Launching ownCloud..."
    adb shell am start -n com.owncloud.android/com.owncloud.android.ui.activity.SplashActivity
    echo "ownCloud should now be running on your emulator."
}

print_installed_version() {
    echo "Installed ownCloud version info:"
    VERSION_INFO=$(adb shell dumpsys package com.owncloud.android | grep -E "versionCode|versionName" || true)
    if [[ -n "$VERSION_INFO" ]]; then
        echo "$VERSION_INFO"
    else
        echo "Could not retrieve version info."
    fi
}

main() {
    echo "ownCloud Android Setup with APK Link"
    echo "====================================="
    echo "Setting up ownCloud Android"
    local apk_link="$1"
    install_owncloud "$apk_link"
    launch_owncloud
    print_installed_version
    echo ""
    echo "Setup complete! ownCloud is ready for testing."
}

main "$@"