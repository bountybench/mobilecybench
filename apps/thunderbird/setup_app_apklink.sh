#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "$SCRIPT_DIR"

# ============================================================================
# Download Thunderbird APK from release
# ============================================================================

download_thunderbird() {
    mkdir -p "${SCRIPT_DIR}/apk"

    download_link=$(jq -r '.download_link' "metadata.json")
    APK_PATH="${SCRIPT_DIR}/apk/app-thunderbird-full-release.apk"

    echo "Downloading Thunderbird APK from: $download_link"
    curl -L -o "$APK_PATH" "$download_link"
    
    echo "APK downloaded successfully to: $APK_PATH"
}

# ============================================================================
# Main
# ============================================================================

main() {
    download_thunderbird
}

main "$@"

