#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
ANDROID_HOME="${HOME}/.android-sdk"
source "$ROOT_DIR/utils/android.sh"

# Check prerequisites
check_prerequisites() {
    echo "Checking prerequisites..."
    
    # Check Java 17
    if ! command -v java >/dev/null 2>&1; then
        echo "ERROR: Java not found. Please install Java 17."
        exit 1
    fi

    if [[ ! -d "$ANDROID_HOME" && -d "/usr/local/lib/android/sdk" ]]; then
        ANDROID_HOME="/usr/local/lib/android/sdk"
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
    if [[ -d "/opt/homebrew/opt/openjdk@17" ]]; then
        export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
    elif [[ -d "/usr/lib/jvm/java-17-openjdk" ]]; then
        export JAVA_HOME=/usr/lib/jvm/java-17-openjdk
    elif command -v /usr/libexec/java_home &>/dev/null; then
        export JAVA_HOME="$(/usr/libexec/java_home -v 17)"
    else
        export JAVA_HOME=$(java -XshowSettings:properties -version 2>&1 | grep 'java.home' | awk '{print $3}')
    fi
    echo $JAVA_HOME
    export PATH="$JAVA_HOME/bin:$PATH"
    
    # Set Android SDK
    export ANDROID_HOME="$ANDROID_HOME"
    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
    
    # Create local.properties for joplin build
    echo "sdk.dir=$ANDROID_HOME" > local.properties
    
    echo "Environment configured."
}

# Build joplin APK
build_joplin() {    
    echo "Building joplin Android from source..."
    echo "This will take several minutes..."
    
    #./gradlew assembleDebug
    #echo "Build completed successfully."

    local temp_out=$(mktemp)
    local temp_err=$(mktemp)
    
    # Run gradle build with output suppressed
    if ./gradlew assembleDebug > "$temp_out" 2> "$temp_err"; then
        echo "Build completed successfully."
        # Clean up temp files on success
        rm -f "$temp_out" "$temp_err"
    else
        local exit_code=$?
        echo "ERROR: Build failed with exit code $exit_code"
        
        # Show stderr (which contains the actual error messages)
        if [[ -s "$temp_err" ]]; then
            echo "Error output:"
            cat "$temp_err"
        fi
        
        # Optionally show last part of stdout for context
        if [[ -s "$temp_out" ]]; then
            echo "Last 50 lines of build output:"
            tail -50 "$temp_out"
        fi
        
        # Clean up temp files
        rm -f "$temp_out" "$temp_err"
        exit $exit_code
    fi
}

# Install on emulator
install_joplin() {
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
    adb_launch_activity "net.cozic.joplin/.MainActivity"
    echo "joplin should now be running on your emulator."
}

# Synching with server
synch_with_server() {
    echo "Synching app with server..."
    pip install uiautomator2
    python synch_app.py --username usera@localhost --password userAPW123
    echo "Should now be synched with server."
}

# Main function
main() {
    echo "joplin Android Setup"
    echo "==================="
    
    echo "Setting up joplin Android"

    npm uninstall -g react-native-cli @react-native-community/cli
    cd codebase
    npm uninstall -g react-native-cli @react-native-community/cli
    #yarn install
    cd -

    root_dir="$(pwd)"

    if [[ -d "codebase/packages/app-mobile" ]]; then
        echo "Navigating to codebase/packages/app-mobile directory..."
        cd codebase/packages/app-mobile
    else
        echo "ERROR: Not in joplin Android directory and codebase/packages/app-mobile/ not found."
        exit 1
    fi

    yarn install
    npx react-native start --reset-cache > /dev/null 2>&1 &
    
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
    
    echo ""
    echo "Setup complete! joplin is ready for testing."
}

# Run main function
main "$@"