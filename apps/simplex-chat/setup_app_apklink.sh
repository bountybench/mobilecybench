#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="${SCRIPT_DIR}/setup_app_apklink.log"

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Error handling
error_exit() {
    log "ERROR: $1"
    exit 1
}

# Download file with progress
download_file() {
    local url="$1"
    local output="$2"

    if command -v curl >/dev/null 2>&1; then
        curl -L --progress-bar "$url" -o "$output"
    elif command -v wget >/dev/null 2>&1; then
        wget --progress=bar:force "$url" -O "$output"
    else
        error_exit "Neither curl nor wget found. Please install one of them."
    fi
}

# Main function
main() {
    log "Starting SimpleX Chat APK download"

    local app_dir="${SCRIPT_DIR}/apps/simplex-chat"
    local apk_dir="$app_dir/apk"
    local apk_file="$apk_dir/simplex-chat.apk"

    # Create directories
    mkdir -p "$apk_dir"

    # Load download URL from metadata
    local metadata_file="${SCRIPT_DIR}/metadata.json"
    local download_url=""

    if [[ -f "$metadata_file" ]]; then
        download_url=$(python3 -c "
import json
try:
    with open('$metadata_file', 'r') as f:
        data = json.load(f)
    print(data.get('download_link', ''))
except:
    print('')
")
    fi

    if [[ -z "$download_url" ]]; then
        download_url="https://github.com/simplex-chat/simplex-chat/releases/latest/download/simplex.apk"
        log "Using default download URL: $download_url"
    else
        log "Using download URL from metadata: $download_url"
    fi

    # Download APK
    log "Downloading SimpleX Chat APK..."
    if download_file "$download_url" "$apk_file"; then
        local apk_size=$(du -h "$apk_file" | cut -f1)
        log "APK downloaded successfully (size: $apk_size)"

        # Verify APK (basic check)
        if [[ -f "$apk_file" ]]; then
            local file_type=$(file "$apk_file" 2>/dev/null || echo "unknown")
            if [[ "$file_type" == *"Android package"* ]] || [[ "$file_type" == *"Zip archive"* ]]; then
                log "APK file appears to be valid"
            else
                log "Warning: Downloaded file may not be a valid APK"
            fi
        fi

        log "SimpleX Chat APK ready at: $apk_file"
        echo ""
        echo "APK downloaded successfully!"
        echo "Location: $apk_file"
        echo ""
        echo "Next steps:"
        echo "1. Run ./setup.sh to set up the emulator and install the APK"
        echo "2. Or manually install with: adb install $apk_file"

        return 0
    else
        error_exit "Failed to download APK from $download_url"
    fi
}

# Run main function
main "$@"
