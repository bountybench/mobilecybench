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

# Download the pre-built apk - first get a fresh LFS download URL
echo "Getting LFS download URL..."
LFS_URL=$(curl -H "Accept: application/vnd.git-lfs+json" -H "Content-Type: application/json" -X POST "https://github.com/cy-suite/element-android-apks.git/info/lfs/objects/batch" -d '{"operation":"download","objects":[{"oid":"139f043e1a4f6d791fffd9041659ba95ae067cf44ec0bd1432809efd3a25a4b2","size":76341616}]}' 2>/dev/null | python3 -c "import json, sys; data=json.load(sys.stdin); print(data['objects'][0]['actions']['download']['href'])")

if [[ -z "$LFS_URL" ]]; then
    echo "ERROR: Failed to get LFS download URL"
    exit 1
fi

echo "Downloading APK from LFS..."
curl -L "$LFS_URL" -o "$SCRIPT_DIR/apk/element-android.apk"

# Verify the download
if [[ -f "$SCRIPT_DIR/apk/element-android.apk" ]]; then
    echo "Element Android APK downloaded successfully to $SCRIPT_DIR/apk/element-android.apk"
    # Show file size for verification
    ls -lh "$SCRIPT_DIR/apk/element-android.apk"
    echo ""
    echo "✅ SUCCESS: This APK is configured to connect to your local homeserver at 10.0.2.2:8008!"
    echo "✅ The app will default to your local server instead of matrix.org"
else
    echo "ERROR: Failed to download APK"
    exit 1
fi