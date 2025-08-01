#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANDROID_HOME="${HOME}/.android-sdk"

# Check prerequisites
check_prerequisites() {
    echo "Checking prerequisites..."
    
    # Check Java
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
    
    # Set Java (adjust path as needed for your system)
    if [[ -d "/opt/homebrew/opt/openjdk@17" ]]; then
        export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
    elif [[ -d "/usr/lib/jvm/java-17-openjdk" ]]; then
        export JAVA_HOME=/usr/lib/jvm/java-17-openjdk
    else
        echo "WARNING: Could not find Java 17. Using system default."
        export JAVA_HOME=$(java -XshowSettings:properties -version 2>&1 | grep 'java.home' | awk '{print $3}')
    fi
    
    export PATH="$JAVA_HOME/bin:$PATH"
    
    # Set Android SDK
    export ANDROID_HOME="$ANDROID_HOME"
    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
    
    # Create local.properties for ownCloud build (in codebase directory)
    echo "sdk.dir=$ANDROID_HOME" > "$SCRIPT_DIR/codebase/local.properties"
    
    echo "Environment configured."
}

# Build ownCloud APK
build_owncloud() {
    echo "Building ownCloud from source..."
    echo "This will take several minutes..."
    
    # Initialize git submodules
    git submodule update --init --recursive
    
    # Clean previous builds
    ./gradlew clean
    
    # Build debug APK (skip lint to avoid known issues)
    ./gradlew assembleDebug -x lint
    
    echo "Build completed successfully."
}

# Check installed version
check_installed_version() {
    echo "Checking installed ownCloud version..."
    
    # Check if emulator is running
    if ! adb devices | grep -q "device\|emulator"; then
        echo "ERROR: No Android emulator found."
        echo "Please start the emulator first."
        return 1
    fi
    
    # Check if ownCloud is installed
    INSTALLED_PACKAGES=$(adb shell pm list packages | grep owncloud)
    
    if [[ -z "$INSTALLED_PACKAGES" ]]; then
        echo "ownCloud is not installed on the device."
        return 1
    fi
    
    echo "Installed ownCloud packages:"
    echo "$INSTALLED_PACKAGES"
    
    # Get version information for debug version if available
    if echo "$INSTALLED_PACKAGES" | grep -q "com.owncloud.android.debug"; then
        echo ""
        echo "Debug version details:"
        VERSION_INFO=$(adb shell dumpsys package com.owncloud.android.debug | grep -E "versionCode|versionName")
        echo "$VERSION_INFO"
        
        # Check APK path and compare with built version
        echo ""
        echo "Checking for built APK files..."
        
        # Find the actual built APK dynamically
        BUILT_APK=$(find owncloudApp/build/outputs/apk/original/debug/ -name "*-original-debug.apk" -type f 2>/dev/null | head -1)
        
        if [[ -n "$BUILT_APK" ]]; then
            echo "Found built APK: $BUILT_APK"
            BUILT_APK_SIZE=$(stat -f%z "$BUILT_APK" 2>/dev/null || echo "Unknown")
            echo "Built APK size: $BUILT_APK_SIZE bytes"
        else
            echo "No built APK found in owncloudApp/build/outputs/apk/original/debug/"
            echo "Available APK files:"
            find owncloudApp/build/outputs -name "*.apk" -type f 2>/dev/null | head -5
        fi
    fi
    
    # Get version information for release version if available
    if echo "$INSTALLED_PACKAGES" | grep -q "com.owncloud.android"; then
        echo ""
        echo "Release version details:"
        VERSION_INFO=$(adb shell dumpsys package com.owncloud.android | grep -E "versionCode|versionName")
        echo "$VERSION_INFO"
    fi
    
    # Check installation time
    echo ""
    echo "Installation details:"
    if echo "$INSTALLED_PACKAGES" | grep -q "com.owncloud.android.debug"; then
        INSTALL_TIME=$(adb shell dumpsys package com.owncloud.android.debug | grep -E "firstInstallTime|lastUpdateTime")
        echo "Debug version:"
        echo "$INSTALL_TIME"
    fi
    
    if echo "$INSTALLED_PACKAGES" | grep -q "com.owncloud.android"; then
        INSTALL_TIME=$(adb shell dumpsys package com.owncloud.android | grep -E "firstInstallTime|lastUpdateTime")
        echo "Release version:"
        echo "$INSTALL_TIME"
    fi
    
    echo ""
    echo "Version check completed."
}

# Install on emulator
install_owncloud() {
    echo "Installing ownCloud on Android emulator..."
    
    # Check if emulator is running
    if ! adb devices | grep -q "device\|emulator"; then
        echo "ERROR: No Android emulator found."
        echo "Please start the emulator first."
        exit 1
    fi
    
    # Find the built APK (use original debug version for vulnerability testing)
    echo "Looking for built APK..."
    APK_PATH=$(find owncloudApp/build/outputs/apk/original/debug/ -name "*-original-debug.apk" -type f 2>/dev/null | head -1)
    
    if [[ -z "$APK_PATH" ]]; then
        echo "ERROR: No original debug APK found in owncloudApp/build/outputs/apk/original/debug/"
        echo "Available APKs:"
        find owncloudApp/build/outputs -name "*.apk" -type f 2>/dev/null | head -10
        exit 1
    fi
    
    echo "Found APK: $APK_PATH"
    
    # Uninstall previous version if exists
    echo "Uninstalling previous version (if exists)..."
    adb uninstall com.owncloud.android 2>/dev/null || true
    adb uninstall com.owncloud.android.debug 2>/dev/null || true
    
    # Install new APK
    adb install "$APK_PATH"
    echo "ownCloud installed successfully."
}

# Launch ownCloud
launch_owncloud() {
    echo "Launching ownCloud..."
    
    # Launch the app (try debug package first, then regular)
    if adb shell pm list packages | grep -q "com.owncloud.android.debug"; then
        echo "Launching debug version..."
        adb shell am start -n com.owncloud.android.debug/com.owncloud.android.ui.activity.SplashActivity
        PACKAGE_NAME="com.owncloud.android.debug"
    else
        echo "Launching release version..."
        adb shell am start -n com.owncloud.android/com.owncloud.android.ui.activity.SplashActivity
        PACKAGE_NAME="com.owncloud.android"
    fi
    
    # Wait a moment and check if app launched
    sleep 3
    
    # Verify the app is running
    if adb shell dumpsys window | grep -q "mCurrentFocus.*$PACKAGE_NAME"; then
        echo "ownCloud launched successfully!"
    else
        echo "ownCloud may not have launched properly."
        echo "Please check your emulator manually."
    fi
}

# Main function
main() {
    echo "ownCloud Android Setup"
    echo "====================="
    
    # Check for command line arguments
    if [[ "$1" == "check-version" ]]; then
        echo "Checking installed ownCloud version..."
        
        # Navigate to owncloud codebase directory for version check
        CODEBASE_DIR="$SCRIPT_DIR/codebase"
        if [[ -d "$CODEBASE_DIR" ]]; then
            cd "$CODEBASE_DIR"
        fi
        
        check_installed_version
        exit 0
    fi
    
    echo "Setting up ownCloud Android from current git checkout"
    
    # Navigate to owncloud codebase directory
    CODEBASE_DIR="$SCRIPT_DIR/codebase"
    if [[ ! -d "$CODEBASE_DIR" ]]; then
        echo "ERROR: ownCloud codebase directory not found at $CODEBASE_DIR"
        echo "Please ensure the codebase directory exists."
        exit 1
    fi
    
    cd "$CODEBASE_DIR"
    
    if [[ ! -f "gradlew" ]]; then
        echo "ERROR: gradlew not found in codebase directory."
        echo "Please ensure you're in the correct ownCloud project directory."
        exit 1
    fi
    
    check_prerequisites
    setup_environment
    build_owncloud
    install_owncloud
    launch_owncloud
    
    echo ""
    echo "=========================================="
    echo "Setup complete! ownCloud is ready for testing."
    echo "=========================================="
    echo ""
    echo "Next steps:"
    echo "1. The app should now be running on your emulator"
    echo "2. You can interact with it manually or run automated tests"
    echo "3. Check the app permissions and server connection capabilities"
    echo ""
    echo "Useful commands:"
    echo "  ./setup_app.sh check-version                    # Check installed version"
    echo "  adb shell am start -n com.owncloud.android.debug/com.owncloud.android.ui.activity.SplashActivity"
    echo "  adb shell dumpsys package com.owncloud.android.debug"
    echo "  adb shell pm list permissions com.owncloud.android.debug"
    echo "  adb logcat | grep owncloud"
    echo ""
    echo "APK Location: owncloudApp/build/outputs/apk/original/debug/<version>-original-debug.apk"
    echo "Package Name: com.owncloud.android.debug (debug) / com.owncloud.android (release)"
    echo "Main Activity: com.owncloud.android.ui.activity.SplashActivity"
    echo ""
}

# Run main function
main "$@"