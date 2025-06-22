
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
    export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
    export PATH="$JAVA_HOME/bin:$PATH"
    
    # Set Android SDK
    export ANDROID_HOME="$ANDROID_HOME"
    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
    
    # Create local.properties for Signal build
    echo "sdk.dir=$ANDROID_HOME" > local.properties
    
    echo "Environment configured."
}

# Build Signal APK
build_signal() {
    echo "Building Signal Android from source..."
    echo "This will take several minutes..."
    
    ./gradlew assemblePlayProdDebug
    
    echo "Build completed successfully."
}

# Install on emulator
install_signal() {
    local version="$1"
    echo "Installing Signal on Android emulator..."
    
    # Check if emulator is running
    if ! adb devices | grep -q "device\|emulator"; then
        echo "ERROR: No Android emulator found."
        echo "Please start the emulator first."
        exit 1
    fi
    
    # Install universal APK with correct path
    APK_PATH="app/build/outputs/apk/playProd/debug/Signal-Android-play-prod-universal-debug-${version}.apk"
    
    if [[ ! -f $APK_PATH ]]; then
        echo "ERROR: APK not found at $APK_PATH"
        echo "Available APKs:"
        find app/build/outputs -name "*.apk" -type f 2>/dev/null | head -10
        exit 1
    fi
    
    adb install "$APK_PATH"
    echo "Signal installed successfully."
}

# Launch Signal
launch_signal() {
    echo "Launching Signal..."
    adb shell am start -n org.thoughtcrime.securesms/.RoutingActivity
    echo "Signal should now be running on your emulator."
}

# Main function
main() {
    echo "Signal Android Setup"
    echo "==================="
    
    # Check for version argument
    if [[ $# -ne 1 ]]; then
        echo "Usage: $0 <version>"
        echo "Example: $0 7.13.4"
        exit 1
    fi
    
    local version="$1"
    echo "Setting up Signal Android version: $version"
    
    # Navigate to codebase directory
    if [[ ! -f "gradlew" ]]; then
        if [[ -d "codebase" ]]; then
            echo "Navigating to codebase directory..."
            cd codebase
        else
            echo "ERROR: Not in Signal Android directory and codebase/ not found."
            echo "Please run this script from the project root or Signal codebase directory."
            exit 1
        fi
    fi
    
    check_prerequisites
    setup_environment
    build_signal
    install_signal "$version"
    launch_signal
    
    echo ""
    echo "Setup complete! Signal version $version is ready for testing."
}

# Run main function
main "$@"