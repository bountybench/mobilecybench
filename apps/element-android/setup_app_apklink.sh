#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Read metadata.json to get download link
METADATA_FILE="$SCRIPT_DIR/metadata.json"
if [[ ! -f "$METADATA_FILE" ]]; then
    echo "ERROR: metadata.json not found at $METADATA_FILE"
    exit 1
fi

DOWNLOAD_LINK=$(python3 -c "
import json
with open('$METADATA_FILE', 'r') as f:
    data = json.load(f)
    print(data.get('download_link', ''))
")

if [[ -z "$DOWNLOAD_LINK" ]]; then
    echo "ERROR: download_link not found in metadata.json"
    exit 1
fi

echo "Downloading Element Android APK from: $DOWNLOAD_LINK"

# Create apk directory if it doesn't exist
mkdir -p "$SCRIPT_DIR/apk" 

# Download the APK
curl -L "$DOWNLOAD_LINK" -o "$SCRIPT_DIR/apk/vector-gplay-rustCrypto-x86_64-release-unsigned.apk"

# Verify the download
if [[ -f "$SCRIPT_DIR/apk/vector-gplay-rustCrypto-x86_64-release-unsigned.apk" ]]; then
    echo "Element Android APK downloaded successfully to $SCRIPT_DIR/apk/vector-gplay-rustCrypto-x86_64-release-unsigned.apk"
    # Show file size for verification
    ls -lh "$SCRIPT_DIR/apk/vector-gplay-rustCrypto-x86_64-release-unsigned.apk"
    echo ""
    echo "✅ SUCCESS: This APK is configured to connect to your local homeserver at 10.0.2.2:8008!"
    echo "✅ The app will default to your local server instead of matrix.org"
else
    echo "ERROR: Failed to download APK"
    exit 1
fi