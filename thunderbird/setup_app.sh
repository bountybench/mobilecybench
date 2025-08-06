#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANDROID_HOME="${HOME}/.android-sdk"

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
    
    # Prefer system JDK 17 discovery
    if JAVA_17="$(/usr/libexec/java_home -v 17 2>/dev/null)"; then
        export JAVA_HOME="$JAVA_17"
    fi
    
    export PATH="$JAVA_HOME/bin:$PATH"
    export ANDROID_HOME="$ANDROID_HOME"
    export ANDROID_SDK_ROOT="$ANDROID_HOME"
    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
    
    # Create local.properties for Thunderbird build
    echo "sdk.dir=$ANDROID_HOME" > local.properties
    
    echo "Environment configured."
}

# Build Thunderbird APK
build_thunderbird() {
    echo "Building Thunderbird Android from source..."
    echo "This will take several minutes..."
    
    ./gradlew :app-thunderbird:assembleFossDebug --no-configuration-cache
    
    echo "Build completed successfully."
}

# Install on emulator
install_thunderbird() {
    echo "Installing Thunderbird on Android emulator..."
    
    # Check if emulator is running
    if ! adb devices | grep -q "device\|emulator"; then
        echo "ERROR: No Android emulator found."
        echo "Please start the emulator first."
        exit 1
    fi
    
    # Install Thunderbird APK
    APK_PATH="app-thunderbird/build/outputs/apk/foss/debug/app-thunderbird-foss-debug.apk"
    
    if [[ ! -f $APK_PATH ]]; then
        echo "ERROR: APK not found at $APK_PATH"
        echo "Available APKs:"
        find . -name "*.apk" -path "*/app-thunderbird/*" -type f 2>/dev/null | head -10
        exit 1
    fi
    
    adb install -r -t "$APK_PATH"
    echo "Thunderbird installed successfully."
}

# Launch Thunderbird
launch_thunderbird() {
    echo "Launching Thunderbird..."
    
    # Try to find and launch Thunderbird package
    PKG="$(adb shell cmd package list packages | tr -d '\r' | grep thunderbird | head -n1 | cut -d: -f2)"
    
    if [[ -z "${PKG:-}" ]]; then
        echo "Could not find Thunderbird package"
        exit 1
    fi
    
    echo "Found package: $PKG"
    adb shell am start -n "$PKG/com.fsck.k9.activity.MessageList"
    echo "Thunderbird should now be running on your emulator."
}

# Main function
main() {
    echo "Thunderbird Android Setup"
    
    # Navigate to codebase directory
    if [[ ! -f "gradlew" ]]; then
        if [[ -d "codebase" ]]; then
            echo "Navigating to codebase directory..."
            cd codebase
        else
            echo "ERROR: Not in Thunderbird Android directory and codebase/ not found."
            echo "Please run this script from the project root or Thunderbird codebase directory."
            exit 1
        fi
    fi
    
    check_prerequisites
    setup_environment
    build_thunderbird
    install_thunderbird
    launch_thunderbird
    
    echo "Thunderbird setup complete!"
}

main "$@"
