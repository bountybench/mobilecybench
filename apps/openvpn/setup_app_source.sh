#!/bin/bash
set -e

echo "Building OpenVPN Android app from source..."

# Check if codebase exists
if [ ! -d "codebase" ]; then
    echo "Error: codebase directory not found."
    echo "The codebase should be checked out to the correct commit version as specified in metadata.json"
    exit 1
fi

# Check for required build tools
MISSING_BUILD_DEPS=()

if ! command -v java >/dev/null 2>&1; then
    MISSING_BUILD_DEPS+=("java")
fi

if ! command -v cmake >/dev/null 2>&1; then
    MISSING_BUILD_DEPS+=("cmake")
fi

if ! command -v swig >/dev/null 2>&1; then
    MISSING_BUILD_DEPS+=("swig")
fi

if [ ${#MISSING_BUILD_DEPS[@]} -ne 0 ]; then
    echo "Error: Missing build dependencies: ${MISSING_BUILD_DEPS[*]}"
    echo "Please install the missing dependencies:"
    echo "  sudo apt update"
    echo "  sudo apt install -y openjdk-17-jdk cmake swig"
    exit 1
fi

# Load metadata
if [ -f "metadata.json" ]; then
    SDK_VERSION=$(python3 -c "import json; print(json.load(open('metadata.json'))['sdk'])")
    JAVA_VERSION=$(python3 -c "import json; print(json.load(open('metadata.json'))['java'])")
    echo "Using SDK version: $SDK_VERSION, Java version: $JAVA_VERSION"
fi

# Build locally
echo "Building OpenVPN Android app locally..."
cd codebase

# Set up build environment
export ANDROID_HOME="${ANDROID_HOME:-$HOME/.android-sdk}"
export PATH="$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"

# Update git submodules
git submodule update --init --recursive

# Clean previous builds
./gradlew clean

# Build the main app (UI variant with OpenVPN 2)
echo "Building OpenVPN Android APK..."
./gradlew :main:assembleUiOvpn2Debug

# Copy APK to parent directory
mkdir -p ../output
cp main/build/outputs/apk/ui/ovpn2/debug/*.apk ../output/ || {
    echo "Warning: Could not find APK files. Checking build outputs:"
    find main/build/outputs -name "*.apk" -type f | head -5
    # Try to copy any APK found
    find main/build/outputs -name "*.apk" -type f -exec cp {} ../output/ \;
}

cd ..

echo "Android APK build completed!"
if [ -d "output" ] && [ "$(ls -A output)" ]; then
    echo "APKs available in: output/"
    ls -la output/
else
    echo "Warning: No APK files found in output directory"
fi