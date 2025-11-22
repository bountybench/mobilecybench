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

# Generate keystore for release signing if it doesn't exist (before entering codebase)
KEYSTORE_PATH="$(pwd)/keystore.jks"
if [ ! -f "$KEYSTORE_PATH" ]; then
    echo "Generating release keystore..."
    keytool -genkey -v -keystore "$KEYSTORE_PATH" \
        -alias openvpn-release \
        -keyalg RSA \
        -keysize 2048 \
        -validity 10000 \
        -storepass android123 \
        -keypass android123 \
        -dname "CN=OpenVPN Release,OU=Development,O=OpenVPN,L=City,S=State,C=US" \
        -noprompt
fi

# Build locally
echo "Building OpenVPN Android app locally..."
cd codebase

# Set up build environment
export ANDROID_HOME="${ANDROID_HOME:-$HOME/.android-sdk}"
export PATH="$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"

# Create gradle.properties with signing config for releaseOvpn2 using absolute path
cat > gradle.properties <<EOF
android.useAndroidX=true
android.enableJetifier=true
android.nonFinalResIds=false
org.gradle.jvmargs=-Xmx2048m -XX:MaxMetaspaceSize=512m -XX:+HeapDumpOnOutOfMemoryError
org.gradle.daemon=true
keystoreO2File=$KEYSTORE_PATH
keystoreO2Password=android123
keystoreO2Alias=openvpn-release
keystoreO2AliasPassword=android123
EOF

# Update git submodules
git submodule update --init --recursive

# Clean previous builds
./gradlew clean

# Build the main app (UI variant with OpenVPN 2)
echo "Building OpenVPN Android APK..."
./gradlew :main:assembleUiOvpn2Release

# Copy APK to standardized path
mkdir -p ../apk
RELEASE_APK="main/build/outputs/apk/uiOvpn2/release/main-ui-ovpn2-universal-release.apk"

if [ -f "$RELEASE_APK" ]; then
    cp "$RELEASE_APK" ../apk/openvpn.apk
    echo "Release APK copied to apk/openvpn.apk"
else
    echo "Error: Release APK not found at expected location: $RELEASE_APK"
    echo "Checking build outputs:"
    find main/build/outputs -name "*.apk" -type f | head -5
    exit 1
fi

cd ..

echo "Android APK build completed!"
if [ -f "apk/openvpn.apk" ]; then
    echo "Release APK available at: apk/openvpn.apk"
    ls -lh apk/openvpn.apk
    echo ""
    echo "Build completed successfully!"
    echo "APK can be installed using: adb install apk/openvpn.apk"
else
    echo "Error: APK build failed - apk/openvpn.apk not found"
    echo "Check build logs above for details"
    exit 1
fi