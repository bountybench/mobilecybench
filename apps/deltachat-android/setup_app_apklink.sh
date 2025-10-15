#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

LOG_PREFIX="[deltachat_setup_app_apklink]"
info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*"; }
error(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*"; exit 1; }

main() {
    METADATA_FILE="$SCRIPT_DIR/metadata.json"
    if [[ ! -f "$METADATA_FILE" ]]; then
        error "metadata.json not found"
    fi

    DOWNLOAD_URL=$(jq -r '.download_link' "$METADATA_FILE")
    if [[ -z "$DOWNLOAD_URL" || "$DOWNLOAD_URL" == "null" ]]; then
        error "download_link not found"
    fi

    APK_DIR="$SCRIPT_DIR/apk"
    mkdir -p "$APK_DIR"

    APK_FILE="$APK_DIR/deltachat-android.apk"

    if command -v curl >/dev/null 2>&1; then
        if ! curl -L -o "$APK_FILE" "$DOWNLOAD_URL"; then
            error "curl download failed"
        fi
    elif command -v wget >/dev/null 2>&1; then
        if ! wget -O "$APK_FILE" "$DOWNLOAD_URL"; then
            error "wget download failed"
        fi
    else
        error "Neither curl nor wget found"
    fi

    if [[ ! -f "$APK_FILE" ]]; then
        error "APK file not found"
    fi

    FILE_SIZE=$(stat -c%s "$APK_FILE" 2>/dev/null || stat -f%z "$APK_FILE" 2>/dev/null || echo "0")
    if [[ "$FILE_SIZE" -lt 1048576 ]]; then
        error "APK too small ($FILE_SIZE bytes)"
    fi

    echo "Download complete! APK ready for installation."
}

main "$@"
