#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Download from git LFS (raw URL)
GITHUB_REPO="cy-suite/element-android-apks"
BRANCH="main"
APK_PATH="v1.6.0-local-homeserver/element-android-universal.apk"

# Git LFS download URL
DOWNLOAD_URL="https://github.com/${GITHUB_REPO}/raw/${BRANCH}/${APK_PATH}"

echo "Downloading Element Android APK (Universal - all architectures)..."

# Create apk directory if it doesn't exist
mkdir -p "$SCRIPT_DIR/apk"

# Check if APK already exists
if [[ -f "$SCRIPT_DIR/apk/element-android.apk" ]]; then
    echo "Element Android APK already exists, skipping download"
    ls -lh "$SCRIPT_DIR/apk/element-android.apk"
    echo ""
    echo "✅ Using existing APK configured for local homeserver at 10.0.2.2:8008!"
else
    echo "Downloading from GitHub Release: $DOWNLOAD_URL"

    # Simple direct download - NO LFS API calls needed!
    curl -L "$DOWNLOAD_URL" -o "$SCRIPT_DIR/apk/element-android.apk"

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
fi
