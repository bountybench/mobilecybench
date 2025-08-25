#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

LOG_PREFIX="[setup_app_source]"
LOG_FILE="${SCRIPT_DIR}/setup_app_source.log"
# Duplicate outputs to console and log file
exec > >(tee -a "$LOG_FILE") 2>&1
info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*"; }
error(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*"; exit 1; }

check_prerequisites() {
    info "Checking prerequisites (Java and Android SDK)..."
    
    # Check Java
    if ! command -v java >/dev/null 2>&1; then
        error "Java not found. Please install Java 17."
    fi

    # More robust check for the Android SDK path.
    if [ -n "$ANDROID_HOME" ] && [ -d "$ANDROID_HOME" ]; then
      info "Using Android SDK from pre-set ANDROID_HOME: $ANDROID_HOME"
    elif [ -d "${HOME}/.android-sdk" ]; then
      # Fallback to the default path if ANDROID_HOME isn't set.
      ANDROID_HOME="${HOME}/.android-sdk"
      info "Found Android SDK at default location: $ANDROID_HOME"
    else
      error "Android SDK not found. Please set the ANDROID_HOME environment variable."
    fi

    
    # Check Android SDK
    if [[ ! -d "$ANDROID_HOME" ]]; then
        error "Android SDK not found at $ANDROID_HOME. Please run the Android emulator setup first."
    fi
    
    info "Prerequisites verified."
}

setup_environment() {
    info "Setting up build environment..."
    
    # Set Java 17
    if [[ -d "/opt/homebrew/opt/openjdk@17" ]]; then
        export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
    elif [[ -d "/usr/lib/jvm/java-17-openjdk" ]]; then
        export JAVA_HOME=/usr/lib/jvm/java-17-openjdk
    else
        warn "Could not find Java 17 via known paths. Using system default."
        export JAVA_HOME=$(java -XshowSettings:properties -version 2>&1 | grep 'java.home' | awk '{print $3}')
    fi
    
    export PATH="$JAVA_HOME/bin:$PATH"
    
    # Set Android SDK
    export ANDROID_HOME="$ANDROID_HOME"
    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
    
    # Create local.properties for ownCloud build (in codebase directory)
    echo "sdk.dir=$ANDROID_HOME" > "$SCRIPT_DIR/codebase/local.properties"
    info "Environment configured."
}

build_owncloud() {
    info "Building ownCloud from source (this may take several minutes)..."
    git submodule update --init --recursive

    ./gradlew clean
    ./gradlew assembleRelease
    info "Build completed successfully."
    sign_apk
}

# Sign the release APK with debug keystore
sign_apk() {
    info "Signing release APK (debug keystore)..."

    KEYSTORE_FILE="$HOME/.android/debug.keystore"
    
    # Check if the debug keystore exists, and create it if it doesn't.
    if [ ! -f "$KEYSTORE_FILE" ]; then
        info "Debug keystore not found. Generating a new one..."
        mkdir -p "$HOME/.android/"
        keytool -genkey -v -keystore "$KEYSTORE_FILE" \
                -alias androiddebugkey -keyalg RSA -keysize 2048 \
                -validity 10000 -storepass android -keypass android \
                -dname "CN=Android Debug, O=Android, C=US"
        info "Debug keystore generated at $KEYSTORE_FILE"
    fi

    APK_UNSIGNED=$(find owncloudApp/build/outputs/apk/original/release/ -name "*-original-release-unsigned.apk" -type f 2>/dev/null | head -1)
    
    if [[ -z "$APK_UNSIGNED" ]]; then
        warn "No unsigned release APK found to sign."
        return 1
    fi
    
    APK_SIGNED="${APK_UNSIGNED/-unsigned.apk/.apk}"
    
    jarsigner -verbose -sigalg SHA1withRSA -digestalg SHA1 -keystore "$HOME/.android/debug.keystore" -storepass android -keypass android "$APK_UNSIGNED" androiddebugkey
    
    mv "$APK_UNSIGNED" "$APK_SIGNED"
    
    info "Signed APK: $APK_SIGNED"
}

check_installed_version() {
    # Check if emulator is running
    if ! adb devices | grep -q "device\|emulator"; then
        error "No Android emulator found. Please start the emulator first."
    fi
    
    # Check if ownCloud is installed
    INSTALLED_PACKAGES=$(adb shell pm list packages | grep owncloud || true)
    
    if [[ -z "$INSTALLED_PACKAGES" ]]; then
        warn "ownCloud not installed on the device. Install before checking version."
        return 1
    fi
    
    info "Installed ownCloud packages:\n$INSTALLED_PACKAGES"
    
    # Get version information for release version if available
    if echo "$INSTALLED_PACKAGES" | grep -q "com.owncloud.android"; then
        echo ""
        echo "Release version details:"
        VERSION_INFO=$(adb shell dumpsys package com.owncloud.android | grep -E "versionCode|versionName")
        echo "$VERSION_INFO"
        
        # Check APK path and compare with built version
        echo ""
        echo "Checking for built APK files..."
        
        # Find the actual built APK dynamically
        BUILT_APK=$(find owncloudApp/build/outputs/apk/original/release/ -name "*-original-release.apk" -type f 2>/dev/null | head -1)
        
        if [[ -n "$BUILT_APK" ]]; then
            echo "Found built APK: $BUILT_APK"
            BUILT_APK_SIZE=$(stat -f%z "$BUILT_APK" 2>/dev/null || echo "Unknown")
            echo "Built APK size: $BUILT_APK_SIZE bytes"
        else
            echo "No built APK found in owncloudApp/build/outputs/apk/original/release/"
            echo "Available APK files:"
            find owncloudApp/build/outputs -name "*.apk" -type f 2>/dev/null | head -5
        fi
    fi
    
    # Check installation time
    echo ""
    echo "Installation details:"
    if echo "$INSTALLED_PACKAGES" | grep -q "com.owncloud.android"; then
        INSTALL_TIME=$(adb shell dumpsys package com.owncloud.android | grep -E "firstInstallTime|lastUpdateTime")
        echo "Release version:"
        echo "$INSTALL_TIME"
    fi
    
    echo ""
    echo "Version check completed."
}

install_owncloud() {
    info "Installing ownCloud on Android emulator..."
    
    # Check if emulator is running
    if ! adb devices | grep -q "device\|emulator"; then
        error "No Android emulator found. Please start the emulator first."
    fi
    
    # Find the built APK
    echo "Looking for built APK..."
    APK_PATH=$(find owncloudApp/build/outputs/apk/original/release/ -name "*-original-release.apk" -type f 2>/dev/null | head -1)
    
    if [[ -z "$APK_PATH" ]]; then
        warn "No original release APK found. Listing available APKs (first 10):"
        find owncloudApp/build/outputs -name "*.apk" -type f 2>/dev/null | head -10
        error "Cannot proceed without APK."
    fi
    
    info "Found APK: $APK_PATH"
    info "Uninstalling previous versions if present"
    adb uninstall com.owncloud.android 2>/dev/null || true
    adb uninstall com.owncloud.android.debug 2>/dev/null || true
    adb install "$APK_PATH"
    info "ownCloud installed successfully."
}

launch_owncloud() {
    info "Launching ownCloud..."
    
    # Launch the app
    if adb shell pm list packages | grep -q "com.owncloud.android" && ! adb shell pm list packages | grep -q "com.owncloud.android.debug"; then
        info "Launching release version"
        adb shell am start -n com.owncloud.android/com.owncloud.android.ui.activity.SplashActivity
        PACKAGE_NAME="com.owncloud.android"
    elif adb shell pm list packages | grep -q "com.owncloud.android.debug"; then
        info "Launching debug version"
        adb shell am start -n com.owncloud.android.debug/com.owncloud.android.ui.activity.SplashActivity
        PACKAGE_NAME="com.owncloud.android.debug"
    else
        error "No ownCloud package found"
    fi
    
    sleep 1
    
    # Verify the app is running
    if adb shell dumpsys window | grep -q "mCurrentFocus.*$PACKAGE_NAME"; then
        info "ownCloud launched successfully"
    else
        warn "ownCloud may not have launched properly (focus not detected)."
    fi
}


main() {
    info "ownCloud Android Setup"
    echo "====================="
    
    if [[ "$1" == "check-version" ]]; then
        info "Checking installed ownCloud version"
        
        # Navigate to owncloud codebase directory for version check
        CODEBASE_DIR="$SCRIPT_DIR/codebase"
        if [[ -d "$CODEBASE_DIR" ]]; then
            cd "$CODEBASE_DIR"
        fi
        
        check_installed_version
        exit 0
    fi
    
    info "Setting up ownCloud Android from current git checkout"
    
    CODEBASE_DIR="$SCRIPT_DIR/codebase"
    if [[ ! -d "$CODEBASE_DIR" ]]; then
        error "ownCloud codebase directory not found at $CODEBASE_DIR"
    fi
    
    cd "$CODEBASE_DIR"
    
    if [[ ! -f "gradlew" ]]; then
        error "gradlew not found in codebase directory."
    fi
    
    check_prerequisites
    setup_environment
    build_owncloud
    install_owncloud
    launch_owncloud
    
    echo ""
    echo "=========================================="
    info "Setup complete! ownCloud is ready for testing."
    echo "=========================================="
    echo ""
    echo "./setup_app.sh check-version                    # Check installed version"
    echo "Main Activity: com.owncloud.android.ui.activity.SplashActivity"
    echo ""
}

main "$@"