#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANDROID_HOME="${HOME}/.android-sdk"

# Install prereq packages
install_prereqs() {
    echo "Installing tesseract and uiautomator2..."

    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        sudo apt update > /dev/null 2>&1 && sudo apt install -y tesseract-ocr > /dev/null 2>&1
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        brew install tesseract > /dev/null 2>&1
    elif [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
        echo "Please install Tesseract manually from https://github.com/tesseract-ocr/tesseract#windows"
    fi
    pip install uiautomator2 > /dev/null 2>&1
}

# Check prerequisites
check_prerequisites() {
    echo "Checking prerequisites..."
    
    # Check Java 17
    if ! command -v java >/dev/null 2>&1; then
        echo "ERROR: Java not found. Please install Java 17."
        exit 1
    fi
    
    # Check Android SDK
    if [[ ! -d "$ANDROID_HOME" ]]; then
        echo "ERROR: Android SDK not found at $ANDROID_HOME"
        echo "Please run the Android emulator setup first."
        exit 1
    fi
    
    echo "Prerequisites verified."
}

# Setup environment
setup_environment() {
    echo "Setting up build environment..."
    
    # Set Java 17
    export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
    export PATH="$JAVA_HOME/bin:$PATH"
    
    # Set Android SDK
    export ANDROID_HOME="$ANDROID_HOME"
    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
    
    # Create local.properties for Brave build
    echo "sdk.dir=$ANDROID_HOME" > local.properties
    
    echo "Environment configured."
}

# Install on emulator
install_brave() {
    local version="$1"
    echo "Installing Brave on Android emulator..."
    
    # Check if emulator is running
    if ! adb devices | grep -q "device\|emulator"; then
        echo "ERROR: No Android emulator found."
        echo "Please start the emulator first."
        exit 1
    fi

    metadata="metadata.json"
    download_link=$(jq -r '.download_links[]' "$metadata" | grep "$version")
    APK_PATH="brave_v${version}.apk"

    if [[ ! -f "$APK_PATH" ]]; then
        echo "Downloading using download link for version $version: $download_link"
        curl -L -o "$APK_PATH" "$download_link"
    fi

    echo $APK_PATH

    if [[ ! -f $APK_PATH ]]; then
        echo "ERROR: APK not found at $APK_PATH"
        echo "Available APKs:"
        find app/build/outputs -name "*.apk" -type f 2>/dev/null | head -10
        exit 1
    fi
    
    adb install "$APK_PATH"
    echo "Brave installed successfully."
}

# Launch Brave
launch_brave() {
    echo "Launching Brave..."
    adb shell am start -n com.brave.browser/com.google.android.apps.chrome.Main 

    echo "Brave should now be running on your emulator."
}

# Navigates past pop ups
navigate() {
    python navigate_past_popup.py
    adb shell uiautomator dump >/dev/null 2>&1
    BUTTON_BOUNDS=$(adb shell cat /sdcard/window_dump.xml 2>/dev/null | grep -o 'text="Execute PIN Bypass Exploit"[^>]*bounds="[^"]*"' | grep -o 'bounds="[^"]*"' | sed 's/bounds="//;s/"//' || echo "")

    if [[ -n "$BUTTON_BOUNDS" ]]; then
        X1=$(echo "$BUTTON_BOUNDS" | sed 's/\[//g;s/\].*//g' | cut -d',' -f1)
        Y1=$(echo "$BUTTON_BOUNDS" | sed 's/\[//g;s/\].*//g' | cut -d',' -f2)
        X2=$(echo "$BUTTON_BOUNDS" | sed 's/.*\]\[//g;s/\]//g' | cut -d',' -f1)
        Y2=$(echo "$BUTTON_BOUNDS" | sed 's/.*\]\[//g;s/\]//g' | cut -d',' -f2)
        
        CENTER_X=$(( (X1 + X2) / 2 ))
        CENTER_Y=$(( (Y1 + Y2) / 2 ))
        
        adb shell input tap $CENTER_X $CENTER_Y
    else
        adb shell input tap 540 900
    fi
}


# Main function
main() {
    echo "Brave Android Setup"
    echo "==================="
    
    # Check for version argument
    if [[ $# -ne 1 ]]; then
        echo "Usage: $0 <version>"
        echo "Example: $0 1.62.165"
        exit 1
    fi
    
    local version="$1"
    echo "Setting up Brave Android version: $version"
    
    install_prereqs
    check_prerequisites
    setup_environment
    install_brave "$version"
    launch_brave
    navigate
    
    echo "Setup complete! Brave version $version is ready for testing."
}

# Run main function
main "$@"