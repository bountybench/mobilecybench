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
    
    # Set Java 17
    export JAVA_HOME=$(/usr/libexec/java_home -v 17)
    export PATH="$JAVA_HOME/bin:$PATH"
    
    # Set Android SDK
    export ANDROID_HOME="$ANDROID_HOME"
    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
    
    # Create local.properties for joplin build
    echo "sdk.dir=$ANDROID_HOME" > local.properties

    #cd codebase
    #yarn install
    #cd -
    
    echo "Environment configured."
}

# Build joplin APK
build_joplin() {
    echo "Building joplin Android from source..."
    echo "This will take several minutes..."
    
    ./gradlew assembleDebug
    
    echo "Build completed successfully."
}

# Install on emulator
install_joplin() {
    local version="$1"
    echo "Installing joplin on Android emulator..."
    
    # Check if emulator is running
    if ! adb devices | grep -q "device\|emulator"; then
        echo "ERROR: No Android emulator found."
        echo "Please start the emulator first."
        exit 1
    fi
    
    # Install universal APK with correct path
    APK_PATH="app/build/outputs/apk/debug/app-debug.apk"
    
    if [[ ! -f $APK_PATH ]]; then
        echo "ERROR: APK not found at $APK_PATH"
        echo "Available APKs:"
        find app/build/outputs -name "*.apk" -type f 2>/dev/null | head -10
        exit 1
    fi
    
    adb install "$APK_PATH"
    echo "joplin installed successfully."
}

# Launch joplin
launch_joplin() {
    echo "Launching joplin..."
    adb shell am start -n net.cozic.joplin/.MainActivity
    echo "joplin should now be running on your emulator."
}

synch_with_server() {
    echo "Synching app with server..."
    python synch_app.py
    echo "Should now be synched with server."
}

# Main function
main() {
    echo "joplin Android Setup"
    echo "==================="
    
    # Check for version argument
    if [[ $# -ne 1 ]]; then
        echo "Usage: $0 <version>"
        echo "Example: $0 3.2.10"
        exit 1
    fi
    
    local version="$1"
    echo "Setting up joplin Android version: $version"

    root_dir="$(pwd)"

    if [[ -d "codebase/packages/app-mobile" ]]; then
        echo "Navigating to codebase/packages/app-mobile directory..."
        cd codebase/packages/app-mobile
    else
        echo "ERROR: Not in joplin Android directory and codebase/packages/app-mobile/ not found."
        exit 1
    fi

    npx react-native start > /dev/null 2>&1 &
    
    # Navigate to codebase directory
    if [[ -d "android" ]]; then
        echo "Navigating to android directory..."
        cd android
    else
        echo "ERROR: Not in joplin Android directory and codebase/packages/app-mobile/android/ not found."
        exit 1
    fi
    
    check_prerequisites
    setup_environment
    build_joplin
    install_joplin "$version"
    launch_joplin
    cd "$root_dir"
    synch_with_server
    
    echo ""
    echo "Setup complete! joplin version $version is ready for testing."
}

# Run main function
main "$@"