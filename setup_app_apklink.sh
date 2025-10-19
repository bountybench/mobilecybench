#!/bin/bash
set -euo pipefail

# This script is already run from the app directory. It takes in the APK link as the argument.
APP_NAME=$(basename "$PWD")
LOG_PREFIX="[setup_app_apklink]"

# Duplicate outputs to console and log file
info() { printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn() { printf '%s[warn] %s\n' "$LOG_PREFIX" "$*"; }
error() { printf '%s[error] %s\n' "$LOG_PREFIX" "$*" >&2; exit 1; }

download_apk() {
    local url="$1"

    mkdir -p "apk"
    local apk_path="apk/${APP_NAME}.apk"

    info "Downloading APK from $url to $apk_path (overwriting if exists)..."
    if ! curl -L --fail --retry 3 --retry-connrefused -o "$apk_path" "$url"; then
        error "Failed to download APK from $url"
    fi
    if [ ! -s "$apk_path" ]; then
        error "Downloaded APK is empty or invalid: $apk_path"
    fi
    info "Successfully downloaded APK: $apk_path"
}

# Main function
main() {
    info "Starting APK download via metadata.json"
    download_apk "$1"
    info "APK download completed successfully"
}

main "$@"
