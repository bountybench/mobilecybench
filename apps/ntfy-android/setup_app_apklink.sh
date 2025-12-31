#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANDROID_HOME="${HOME}/.android-sdk"
LOG_PREFIX="[setup_app_apklink]"
LOG_FILE="${SCRIPT_DIR}/setup_app_apklink.log"

# Duplicate outputs to console and log file
exec > >(tee -a "$LOG_FILE") 2>&1

info() { printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn() { printf '%s[warn] %s\n' "$LOG_PREFIX" "$*"; }
error() { printf '%s[error] %s\n' "$LOG_PREFIX" "$*" >&2; exit 1; }

# Get download link from metadata.json
get_download_link() {
    local meta_file="${SCRIPT_DIR}/metadata.json"
    
    if [ ! -f "$meta_file" ]; then
        error "metadata.json not found at $meta_file"
    fi
    if ! command -v jq >/dev/null 2>&1; then
        error "jq is required but not installed"
    fi
    
    local link
    link=$(jq -er '.download_link // empty' "$meta_file") || {
        error "download_link not found in $meta_file"
    }
    if [ -z "$link" ]; then
        error "download_link is empty in $meta_file"
    fi
    
    printf '%s\n' "$link"
}

# Download APK to SCRIPT_DIR/apk/ntfy-android.apk
download_apk() {
    local url="$1"
    local apk_dir="${SCRIPT_DIR}/apk"
    local apk_path="${apk_dir}/ntfy-android.apk"
    
    # Create apk directory if it doesn't exist
    mkdir -p "$apk_dir"
    
    info "Downloading ntfy-android APK from $url to $apk_path (overwriting if exists)..."
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
    info "Starting ntfy-android APK download via metadata.json"
    
    local url
    url=$(get_download_link)
    download_apk "$url"
    info "ntfy-android APK download completed successfully"
}

main "$@"

