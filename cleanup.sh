#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="${SCRIPT_DIR}/setup.log"
ANDROID_HOME="${HOME}/.android-sdk"
EMULATOR_NAME="MobileCybenchEmu"

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# Confirmation prompt
confirm() {
    read -p "$1 (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log "Operation cancelled."
        exit 1
    fi
}

# Remove AVD
remove_avd() {
    log "Removing Android Virtual Device: $EMULATOR_NAME"
    if [[ -d "$ANDROID_HOME/cmdline-tools/latest/bin" ]]; then
        "$ANDROID_HOME/cmdline-tools/latest/bin/avdmanager" delete avd -n "$EMULATOR_NAME"
    else
        log "AVD manager not found, manually removing AVD directory."
        rm -rf "$HOME/.android/avd/${EMULATOR_NAME}.avd"
        rm -rf "$HOME/.android/avd/${EMULATOR_NAME}.ini"
    fi
}

# Remove Android SDK
remove_sdk() {
    log "Removing Android SDK at $ANDROID_HOME"
    rm -rf "$ANDROID_HOME"
}

# Remove helper scripts
remove_helpers() {
    log "Removing helper scripts"
    rm -f "${SCRIPT_DIR}/start_emulator.sh"
    rm -f "${SCRIPT_DIR}/stop_emulator.sh"
    rm -f "${SCRIPT_DIR}/check_device.sh"
    rm -f "$LOG_FILE"
}

# Remove environment variables from profile
remove_env_vars() {
    local shell_profile=""
    if [[ -n "$ZSH_VERSION" ]]; then
        shell_profile="$HOME/.zshrc"
    elif [[ -n "$BASH_VERSION" ]]; then
        shell_profile="$HOME/.bashrc"
    fi
    
    if [[ -n "$shell_profile" && -f "$shell_profile" ]]; then
        log "Removing environment variables from $shell_profile"
        sed -i '' '/# Android SDK (added by mobile benchmark setup)/,/^export PATH=/d' "$shell_profile"
    fi
}

# Main cleanup function
main() {
    log "Starting cleanup process"
    confirm "This will remove the Android SDK, emulator, and all related files. Continue?"
    
    remove_avd
    remove_sdk
    remove_helpers
    remove_env_vars
    
    log "Cleanup completed successfully!"
    echo "Note: You may need to restart your terminal or source your profile file."
}

main "$@" 