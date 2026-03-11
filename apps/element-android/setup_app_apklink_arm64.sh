#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Read metadata.json to get download link
METADATA_FILE="$SCRIPT_DIR/metadata.json"
if [[ ! -f "$METADATA_FILE" ]]; then
    echo "ERROR: metadata.json not found at $METADATA_FILE"
    exit 1
fi

echo "Downloading Element Android APK (ARM64)..."

# Create apk directory if it doesn't exist
mkdir -p "$SCRIPT_DIR/apk"

# Download the pre-built ARM64 apk - first get a fresh LFS download URL
echo "Getting LFS download URL for ARM64 APK..."
LFS_URL=$(curl -H "Accept: application/vnd.git-lfs+json" -H "Content-Type: application/json" -X POST "https://github.com/cy-suite/element-android-apks.git/info/lfs/objects/batch" -d '{"operation":"download","objects":[{"oid":"0c6799e523f926d40d7567ef082149b9b2d4dc7b769a3fc3cc2ebf9ac871ab7c","size":88165131}]}' 2>/dev/null | python3 -c "import json, sys; data=json.load(sys.stdin); print(data['objects'][0]['actions']['download']['href'])")

if [[ -z "$LFS_URL" ]]; then
    echo "ERROR: Failed to get LFS download URL"
    exit 1
fi

echo "Downloading ARM64 APK from LFS..."
curl -L "$LFS_URL" -o "$SCRIPT_DIR/apk/element-android-arm64.apk"

# Verify the download
if [[ -f "$SCRIPT_DIR/apk/element-android-arm64.apk" ]]; then
    echo "Element Android APK (ARM64) downloaded successfully to $SCRIPT_DIR/apk/element-android-arm64.apk"
    # Show file size for verification
    ls -lh "$SCRIPT_DIR/apk/element-android-arm64.apk"
    echo ""
    echo "✅ SUCCESS: This ARM64 APK is configured to connect to your local homeserver at 10.0.2.2:8008!"
    echo "✅ The app will default to your local server instead of matrix.org"
else
    echo "ERROR: Failed to download ARM64 APK"
    exit 1
fi
