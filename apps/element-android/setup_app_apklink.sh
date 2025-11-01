#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Building Element Android APK from source..."

# Check if codebase directory exists
if [[ ! -d "$SCRIPT_DIR/codebase" ]]; then
    echo "ERROR: codebase directory not found at $SCRIPT_DIR/codebase"
    echo "Please ensure the Element Android source code is properly cloned."
    exit 1
fi

# Create apk directory if it doesn't exist
mkdir -p "$SCRIPT_DIR/apk"

# Navigate to codebase directory
cd "$SCRIPT_DIR/codebase"

echo "Checking Git LFS status..."
# Handle potential LFS issues gracefully - skip missing LFS files for build
git config --local lfs.fetchexclude 'matrix-sdk-android/src/androidTest/assets/*'

echo "Ensuring gradle wrapper is executable..."
chmod +x gradlew

echo "Building debug APK (this may take several minutes)..."
# Build the debug APK - more suitable for testing
./gradlew assembleGplayRustCryptoDebug --no-daemon --stacktrace

# Find the generated APK
APK_PATH=$(find vector-app/build/outputs/apk -name "*.apk" | grep -E "(debug|universal)" | head -1)

if [[ -z "$APK_PATH" ]]; then
    echo "ERROR: Could not find generated APK"
    echo "Available APKs:"
    find vector-app/build/outputs/apk -name "*.apk" 2>/dev/null || echo "No APKs found"
    exit 1
fi

echo "APK found at: $APK_PATH"

# Copy APK to the expected location
cp "$APK_PATH" "$SCRIPT_DIR/apk/element-android.apk"

# Verify the build
if [[ -f "$SCRIPT_DIR/apk/element-android.apk" ]]; then
    echo "Element Android APK built successfully!"
    echo "APK location: $SCRIPT_DIR/apk/element-android.apk"
    # Show file size for verification
    ls -lh "$SCRIPT_DIR/apk/element-android.apk"
    
    echo ""
    echo "APK Details:"
    file "$SCRIPT_DIR/apk/element-android.apk"
else
    echo "ERROR: Failed to build APK"
    exit 1
fi

echo ""
echo "Build complete! The APK is configured to connect to your local homeserver at localhost:8008"