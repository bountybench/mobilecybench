#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANDROID_HOME="${HOME}/.android-sdk"

LOG_PREFIX="[setup_app_apklink]"
LOG_FILE="${SCRIPT_DIR}/setup_app_apklink.log"
# Duplicate outputs to console and log file
exec > >(tee -a "$LOG_FILE") 2>&1
info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*"; }
error(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*"; exit 1; }

DEFAULT_DOWNLOAD_LINK="https://github.com/owncloud/android/releases/download/oc-android-2.21.2/owncloud_2.21.2-original-release.apk"

install_owncloud() {
    local download_link="$1"
    if [[ -z "$download_link" ]]; then
        download_link="$DEFAULT_DOWNLOAD_LINK"
    fi
    # Check if emulator is running
    if ! adb devices | grep -q "device\|emulator"; then
        error "No Android emulator found. Please start the emulator first."
    fi
    # Uninstall previous ownCloud versions if installed
    info "Checking for installed ownCloud packages..."
    INSTALLED_PACKAGES=$(adb shell pm list packages | grep owncloud || true)
    if [[ -n "$INSTALLED_PACKAGES" ]]; then
        info "Uninstalling previous ownCloud packages..."
        adb uninstall com.owncloud.android 2>/dev/null || true
        adb uninstall com.owncloud.android.debug 2>/dev/null || true
    fi
    APK_PATH="owncloud.apk"
    info "Downloading ownCloud APK from: $download_link"
    curl -L -o "$APK_PATH" "$download_link"
    if [[ ! -f $APK_PATH ]]; then
        error "APK not found at $APK_PATH after download"
    fi
    adb install "$APK_PATH"
    info "ownCloud installed successfully."
}

launch_owncloud() {
    info "Launching ownCloud..."
    adb shell am start -n com.owncloud.android/com.owncloud.android.ui.activity.SplashActivity
    info "ownCloud launched on emulator."
}

print_installed_version() {
    info "Checking installed ownCloud version..."
    VERSION_INFO=$(adb shell dumpsys package com.owncloud.android | grep -E "versionCode|versionName" || true)
    if [[ -n "$VERSION_INFO" ]]; then
        info "Version info:\n$VERSION_INFO"
    else
        warn "Could not retrieve version info."
    fi
}

main() {
    info "ownCloud Android Setup with APK Link"
    info "Setting up ownCloud Android"
    local apk_link="$1"
    install_owncloud "$apk_link"
    launch_owncloud
    print_installed_version
    info "Setup complete! ownCloud is ready for testing."
}

main "$@"