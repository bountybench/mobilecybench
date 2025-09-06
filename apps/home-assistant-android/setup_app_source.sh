#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANDROID_HOME="${HOME}/.android-sdk"


# Check prerequisites
check_prerequisites() {
    echo "Checking prerequisites..."
    if [ ! -d "$ANDROID_HOME" ]; then
        echo "Android SDK not found at $ANDROID_HOME"
        exit 1
    fi
    if ! command -v java >/dev/null 2>&1; then
        echo "Java not found. Please install Java 17."
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
    
    # Create local.properties for Home Assistant build
    echo "sdk.dir=$ANDROID_HOME" > local.properties

    # Generate mock keystore for app/ if it doesn't exist
    if [ ! -f app/release_keystore.keystore ]; then
        keytool -genkeypair -v -keystore app/release_keystore.keystore -alias release -keyalg RSA -keysize 2048 -validity 10000 -storepass android -keypass android -dname "CN=Android Debug,O=Home Assistant,C=US"
    fi
    # Generate mock keystore for wear/ if it doesn't exist
    if [ ! -f wear/release_keystore.keystore ]; then
        keytool -genkeypair -v -keystore wear/release_keystore.keystore -alias release -keyalg RSA -keysize 2048 -validity 10000 -storepass android -keypass android -dname "CN=Android Debug,O=Home Assistant,C=US"
    fi
    # Generate mock keystore for automotive/ if it doesn't exist
    if [ ! -f automotive/release_keystore.keystore ]; then
        keytool -genkeypair -v -keystore automotive/release_keystore.keystore -alias release -keyalg RSA -keysize 2048 -validity 10000 -storepass android -keypass android -dname "CN=Android Debug,O=Home Assistant,C=US"
    fi
    
    # There should be a dummy google-services.json file in the Home Assistant root directory.
    # The Home Assistant app requires Firebase services for all build variants.
    # Copy google-services.json from the Home Assistant root directory to app/google-services.json inside the codebase directory.
    if [ ! -f ../google-services.json ]; then
        echo "ERROR: google-services.json not found in the Home Assistant root directory."
        echo "Please copy a valid google-services.json file to the Home Assistant root directory."
        exit 1
    else
        cp "../google-services.json" "app/google-services.json"
        cp "../google-services.json" "automotive/google-services.json"
        cp "../google-services.json" "wear/google-services.json"

    fi
    
    echo "Environment configured."
}

# Build Home Assistant APK
build_home_assistant() {
    echo "Building Home Assistant from source..."
    echo "This will take several minutes..."
        
    git submodule update --init --recursive

    ./gradlew clean
    ./gradlew assembleMinimalRelease -Dorg.gradle.jvmargs="-Xmx8g"
    echo "Build completed successfully."
}

# Initialize installation of Home Assistant
install_home_assistant() {
    echo "Installing Home Assistant APK on connected device/emulator..."

    # Check if emulator is running
    if ! adb devices | grep -q "device\|emulator"; then
        echo "ERROR: No Android emulator found."
        echo "Please start the emulator first."
        exit 1
    fi

    # Install universal APK with correct path
    APK_PATH="app/build/outputs/apk/minimal/debug/app-minimal-debug.apk"

    if [[ ! -f $APK_PATH ]]; then
        echo "ERROR: APK not found at $APK_PATH"
        echo "Available APKs:"
        find app/build/outputs -name "*.apk" -type f 2>/dev/null | head -10
        exit 1
    fi

    adb install -r "$APK_PATH"
    echo "Installed Home Assistant successfully."
}

# Launch Home Assistant
launch_home_assistant() {
    echo "Launching Home Assistant (from source)..."
    adb shell pm list packages
    adb shell pm grant io.homeassistant.companion.android.minimal android.permission.POST_NOTIFICATIONS
    adb shell monkey -p io.homeassistant.companion.android.minimal -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
    echo "Home Assistant should now be running on your emulator."
}

perform_cleanup() {
    echo "Clearing cache..."
    
    rm -rf app/build/intermediates 2>/dev/null || true
    rm -rf app/build/tmp 2>/dev/null || true
    rm -rf .gradle/buildOutputCleanup/cache.properties 2>/dev/null || true
}

# Main function
main() {
    echo "Home Assistant Setup"
    echo "==================="
    
    # Navigate to codebase directory
    if [[ ! -f "gradlew" ]]; then
        if [[ -d "codebase" ]]; then
            echo "Navigating to codebase directory..."
            cd codebase
        else
            echo "ERROR: Not in Home Assistant directory and codebase/ not found."
        echo "Please run this script from the project root or Home Assistant codebase directory."
            exit 1
        fi
    fi
    
    check_prerequisites
    setup_environment
    build_home_assistant
    install_home_assistant
    launch_home_assistant
    perform_cleanup

    echo "Setup complete! Home Assistant is ready for testing."
}

# Run main
main "$@"