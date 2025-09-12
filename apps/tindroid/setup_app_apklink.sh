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

DEFAULT_DOWNLOAD_LINK="https://github.com/tinode/tindroid/releases/download/v0.24.2/tindroid-debug.apk"

install_tindroid() {
    local download_link="$1"
    if [[ -z "$download_link" ]]; then
        download_link="$DEFAULT_DOWNLOAD_LINK"
    fi
    # Check if emulator is running
    if ! adb devices | grep -q "device\|emulator"; then
        error "No Android emulator found. Please start the emulator first."
    fi
    # Uninstall previous Tindroid versions if installed
    info "Checking for installed Tindroid packages..."
    INSTALLED_PACKAGES=$(adb shell pm list packages | grep tindroid || true)
    if [[ -n "$INSTALLED_PACKAGES" ]]; then
        info "Uninstalling previous Tindroid packages..."
        adb uninstall co.tinode.tindroidx 2>/dev/null || true
        adb uninstall co.tinode.tindroid 2>/dev/null || true
    fi
    APK_PATH="tindroid-debug.apk"
    info "Downloading Tindroid APK from: $download_link"
    curl -L -o "$APK_PATH" "$download_link"
    if [[ ! -f $APK_PATH ]]; then
        error "APK not found at $APK_PATH after download"
    fi
    adb install "$APK_PATH"
    info "Tindroid installed successfully."
}

launch_tindroid() {
    info "Launching Tindroid..."
    adb shell am start -n co.tinode.tindroidx/co.tinode.tindroid.InitRouterActivity
    info "Tindroid launched on emulator."
}

print_installed_version() {
    info "Checking installed Tindroid version..."
    VERSION_INFO=$(adb shell dumpsys package co.tinode.tindroidx | grep -E "versionCode|versionName" || true)
    if [[ -n "$VERSION_INFO" ]]; then
        info "Version info:\n$VERSION_INFO"
    else
        warn "Could not retrieve version info."
    fi
}

main() {
    info "Tindroid Android Setup with APK Link"
    info "Setting up Tindroid Android"
    local apk_link="$1"
    install_tindroid "$apk_link"
    launch_tindroid
    print_installed_version
    info "Setup complete! Tindroid is ready for testing."
}

main "$@"