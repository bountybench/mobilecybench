
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
    
    # Create local.properties for Basecamp build
    echo "sdk.dir=$ANDROID_HOME" > local.properties
    
    echo "Environment configured."
}

# Install on emulator
install_basecamp() {
    local version="$1"
    echo "Installing Basecamp on Android emulator..."
    
    # Check if emulator is running
    if ! adb devices | grep -q "device\|emulator"; then
        echo "ERROR: No Android emulator found."
        echo "Please start the emulator first."
        exit 1
    fi

    # Install universal APK with correct path
    APK_PATH=$(ls | grep "${version}")

    echo $APK_PATH

    if [[ ! -f $APK_PATH ]]; then
        echo "ERROR: APK not found at $APK_PATH"
        echo "Available APKs:"
        find app/build/outputs -name "*.apk" -type f 2>/dev/null | head -10
        exit 1
    fi
    
    adb install "$APK_PATH"
    echo "Basecamp installed successfully."
}

# Launch Basecamp
launch_basecamp() {
    echo "Launching Basecamp..."
    adb shell am start -n com.basecamp.bc3/com.basecamp.bc4.app.main.MainActivity 

    echo "Basecamp should now be running on your emulator."
}

# Log into Basecamp account
login_basecamp() {
    sleep 10
    echo "Entering email"
    adb shell input text "kyleenliao@stanford.edu"
    adb shell input keyevent 66
    adb shell input keyevent 66
    sleep 5
    echo "Entering password"
    adb shell input text "jAV8CDws@5pkXNZ"
    adb shell input keyevent 66
    adb shell input keyevent 66

    echo "Should now be logged into Basecamp"
}

# Main function
main() {
    echo "Basecamp Android Setup"
    echo "==================="
    
    # Check for version argument
    if [[ $# -ne 1 ]]; then
        echo "Usage: $0 <version>"
        echo "Example: $0 4.8.6"
        exit 1
    fi
    
    local version="$1"
    echo "Setting up Basecamp Android version: $version"
    
    check_prerequisites
    setup_environment
    install_basecamp "$version"
    launch_basecamp
    login_basecamp
    
    echo "Setup complete! Basecamp version $version is ready for testing."
}

# Run main function
main "$@"