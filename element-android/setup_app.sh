#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANDROID_HOME="${HOME}/.android-sdk"

# Check prerequisites
check_prerequisites() {
    echo "Checking prerequisites..."
    
    # Check Java 11
    if ! command -v java >/dev/null 2>&1; then
        echo "ERROR: Java not found. Please install Java 11."
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
    
    # Set Java 11
    export JAVA_HOME=/opt/homebrew/opt/openjdk@11/libexec/openjdk.jdk/Contents/Home
    export PATH="$JAVA_HOME/bin:$PATH"
    
    # Set Android SDK
    export ANDROID_HOME="$ANDROID_HOME"
    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
    
    # Create local.properties for Element build
    echo "sdk.dir=$ANDROID_HOME" > local.properties
    
    echo "Environment configured."
}

# Build Element APK
build_element() {
    echo "Building Element Android from source..."
    echo "This will take several minutes..."
    
    # Stop daemon and set memory options
    ./gradlew --stop
    export GRADLE_OPTS="-Xmx8g -XX:MaxMetaspaceSize=2g"
    
    ./gradlew assembleGplayDebug
    
    echo "Build completed successfully."
}

# Install on emulator
install_element() {
    echo "Installing Element on Android emulator..."
    
    # Check if emulator is running
    if ! adb devices | grep -q "device\|emulator"; then
        echo "ERROR: No Android emulator found."
        echo "Please start the emulator first."
        exit 1
    fi
    
    # Install universal APK
    APK_PATH="vector-app/build/outputs/apk/gplay/debug/vector-gplay-universal-debug.apk"
    
    if [[ ! -f $APK_PATH ]]; then
        echo "ERROR: APK not found at $APK_PATH"
        echo "Available APKs:"
        find vector-app/build/outputs -name "*.apk" -type f 2>/dev/null | head -10
        exit 1
    fi
    
    adb install "$APK_PATH"
    echo "Element installed successfully."
}

# Launch Element directly
launch_element() {
    echo "Launching Element..."
    
    # Launch Element using component name
    adb shell am start -n im.vector.app.debug/im.vector.application.features.Alias
    
    # Verify launch
    sleep 2
    if adb shell dumpsys window | grep -q "mCurrentFocus.*im.vector.app"; then
        echo "Successfully launched Element!"
        return 0
    else
        echo "Element may not have launched properly."
        echo "Trying alternative launch method..."
        
        # Try launching MainActivity directly as fallback
        adb shell am start -n im.vector.app.debug/im.vector.app.features.MainActivity
        sleep 2
        
        if adb shell dumpsys window | grep -q "mCurrentFocus.*im.vector.app"; then
            echo "Successfully launched Element with alternative method!"
            return 0
        else
            echo "Element may not have launched properly."
            echo "Please check your emulator - Element should be installed."
            return 1
        fi
    fi
}

# Main function
main() {
    echo "Element Android Setup"
    echo "===================="
    
    echo "Setting up Element Android from current git checkout"
    
    # Navigate to codebase directory
    if [[ ! -f "gradlew" ]]; then
        if [[ -d "codebase" ]]; then
            echo "Navigating to codebase directory..."
            cd codebase
        else
            echo "ERROR: Not in Element Android directory and codebase/ not found."
            echo "Please run this script from the project root or Element codebase directory."
            exit 1
        fi
    fi
    
    check_prerequisites
    setup_environment
    build_element
    install_element
    
    echo ""
    echo "=========================================="
    echo "Setup complete! Element has been installed."
    echo "=========================================="
    echo ""
    echo "Launching Element..."
    
    if launch_element; then
        echo "Element is now running and ready for mobile security testing!"
    else
        echo "Please manually launch Element from your emulator."
        echo "You can also try running: adb shell am start -n im.vector.app.debug/im.vector.application.features.Alias"
    fi
    
    echo ""
    echo "Element setup completed successfully!"
}

# Run main function
main