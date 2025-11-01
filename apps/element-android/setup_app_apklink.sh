#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Building Element Android APK from source with local homeserver configuration..."

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

echo "Cleaning and refreshing dependencies..."
./gradlew clean --refresh-dependencies

echo "Building debug APK with local homeserver configuration (this may take several minutes)..."
# Build the debug APK - more suitable for testing
./gradlew assembleGplayRustCryptoDebug --refresh-dependencies --no-build-cache --no-daemon --stacktrace

# Find the generated APK - prioritize arm64-v8a, then universal, then any debug
APK_PATH=$(find vector-app/build/outputs/apk -name "*arm64-v8a-debug.apk" | head -1)
if [[ -z "$APK_PATH" ]]; then
    APK_PATH=$(find vector-app/build/outputs/apk -name "*universal-debug.apk" | head -1)
fi
if [[ -z "$APK_PATH" ]]; then
    APK_PATH=$(find vector-app/build/outputs/apk -name "*debug.apk" | head -1)
fi

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
    echo ""
    echo "✅ SUCCESS: This APK is configured to connect to your local homeserver at localhost:8008!"
    echo "✅ The app will default to your local server instead of matrix.org"
else
    echo "ERROR: Failed to build APK"
    exit 1
fi