#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

LOG_PREFIX="[deltachat_setup_app_apklink]"
info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*"; }
error(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*"; exit 1; }

main() {
    info "DeltaChat Android APK Download"
    echo "==============================="
    
    # Read download link from metadata.json
    METADATA_FILE="$SCRIPT_DIR/metadata.json"
    if [[ ! -f "$METADATA_FILE" ]]; then
        error "metadata.json not found at $METADATA_FILE"
    fi
    
    DOWNLOAD_URL=$(jq -r '.download_link' "$METADATA_FILE")
    if [[ -z "$DOWNLOAD_URL" || "$DOWNLOAD_URL" == "null" ]]; then
        error "download_link not found in metadata.json"
    fi
    
    info "Download URL: $DOWNLOAD_URL"
    
    # Create APK directory
    APK_DIR="$SCRIPT_DIR/apk"
    mkdir -p "$APK_DIR"
    
    # Download APK with standardized name
    APK_FILE="$APK_DIR/deltachat-android.apk"
    
    info "Downloading APK to $APK_FILE..."
    if command -v curl >/dev/null 2>&1; then
        if ! curl -L -o "$APK_FILE" "$DOWNLOAD_URL"; then
            error "Failed to download APK using curl"
        fi
    elif command -v wget >/dev/null 2>&1; then
        if ! wget -O "$APK_FILE" "$DOWNLOAD_URL"; then
            error "Failed to download APK using wget"
        fi
    else
        error "Neither curl nor wget found. Cannot download APK."
    fi
    
    # Verify APK was downloaded
    if [[ ! -f "$APK_FILE" ]]; then
        error "APK file not found after download"
    fi
    
    # Check file size (should be > 1MB for a valid APK)
    FILE_SIZE=$(stat -c%s "$APK_FILE" 2>/dev/null || stat -f%z "$APK_FILE" 2>/dev/null || echo "0")
    if [[ "$FILE_SIZE" -lt 1048576 ]]; then
        error "Downloaded APK file is too small ($FILE_SIZE bytes). Download may have failed."
    fi
    
    info "APK downloaded successfully:"
    ls -lh "$APK_FILE"
    
    echo ""
    echo "Download complete! DeltaChat APK is ready for installation."
}

main "$@"
