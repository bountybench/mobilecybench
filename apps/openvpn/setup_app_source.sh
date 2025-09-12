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
    
    # Check if emulator is running - only install if available
    echo "Checking for Android emulator..."
    export ANDROID_HOME="${ANDROID_HOME:-$HOME/.android-sdk}"
    export PATH="$ANDROID_HOME/platform-tools:$PATH"
    
    if ! adb devices | grep -q "emulator.*device"; then
        echo "Warning: No emulator detected. Skipping APK installation."
        echo "APK build completed successfully. Install manually if needed."
        exit 0
    fi
    
    # Install APK on emulator
    echo "Installing APK on emulator..."
    
    # Find the best APK to install (prefer universal, then x86_64)
    APK_FILE=""
    if [ -f "output/main-ui-ovpn2-universal-debug.apk" ]; then
        APK_FILE="output/main-ui-ovpn2-universal-debug.apk"
    elif [ -f "output/main-ui-ovpn2-x86_64-debug.apk" ]; then
        APK_FILE="output/main-ui-ovpn2-x86_64-debug.apk" 
    else
        APK_FILE=$(ls output/*.apk | head -1)
    fi
    
    if [ -n "$APK_FILE" ]; then
        echo "Installing APK: $APK_FILE"
        
        # Uninstall existing version
        adb uninstall de.blinkt.openvpn 2>/dev/null || echo "No existing app to uninstall"
        
        # Install new APK
        adb install "$APK_FILE"
        
        # Push OpenVPN config if available
        if [ -f "client-configs/android-client.ovpn" ]; then
            echo "Copying OpenVPN config to emulator..."
            adb push client-configs/android-client.ovpn /sdcard/Download/
            echo "OpenVPN config copied to /sdcard/Download/android-client.ovpn"
        fi
        
        # Launch the app
        echo "Launching OpenVPN app..."
        adb shell am start -n de.blinkt.openvpn/de.blinkt.openvpn.LaunchVPN
        
        # Wait for app to start
        sleep 3
        
        # Check if app launched successfully
        if adb shell dumpsys package de.blinkt.openvpn | grep -q "ACTIVITY"; then
            echo "✓ OpenVPN app launched successfully"
            echo ""
            echo "Setup completed! Next steps:"
            echo "1. Open the OpenVPN app on the emulator"
            echo "2. Import the client configuration from /sdcard/Download/android-client.ovpn"
            echo "3. Connect to the VPN server at 10.0.2.2:1194"
        else
            echo "⚠ App may not have launched properly"
        fi
        
    else
        echo "Error: No APK files found to install"
        exit 1
    fi
else
    echo "Error: No APK files found in output directory"
    echo "Build may have failed - check build logs above"
    exit 1
fi