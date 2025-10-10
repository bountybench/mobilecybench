#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Read metadata
METADATA_FILE="$SCRIPT_DIR/metadata.json"
if [[ ! -f "$METADATA_FILE" ]]; then
    echo "ERROR: metadata.json not found at $METADATA_FILE"
    exit 1
fi

# Extract download link from metadata.json
DOWNLOAD_LINK=$(python3 -c "import json; print(json.load(open('$METADATA_FILE'))['download_link'])")

if [[ -z "$DOWNLOAD_LINK" ]]; then
    echo "ERROR: download_link not found in metadata.json"
    exit 1
fi

echo "Download link: $DOWNLOAD_LINK"

# Create apk directory
mkdir -p "$SCRIPT_DIR/apk"

# Download APK
echo "Downloading Brave APK..."
curl -L -o "$SCRIPT_DIR/apk/brave.apk" "$DOWNLOAD_LINK"

# Verify APK was downloaded
if [[ ! -f "$SCRIPT_DIR/apk/brave.apk" ]]; then
    echo "ERROR: Failed to download APK"
    exit 1
fi

# Check APK size (should be more than 1MB)
APK_SIZE=$(stat -f%z "$SCRIPT_DIR/apk/brave.apk" 2>/dev/null || stat -c%s "$SCRIPT_DIR/apk/brave.apk" 2>/dev/null)
if [[ $APK_SIZE -lt 1048576 ]]; then
    echo "ERROR: Downloaded APK seems too small ($APK_SIZE bytes). Download may have failed."
    exit 1
fi

echo "Brave APK downloaded successfully to: $SCRIPT_DIR/apk/brave.apk"
echo "APK size: $APK_SIZE bytes"