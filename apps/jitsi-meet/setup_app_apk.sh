#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
ANDROID_HOME="${HOME}/.android-sdk"
source "$ROOT_DIR/utils/android.sh" || true
: "${AVD_NAME:=Pixel_2_API_28}"

check_prerequisites() {
    echo "Checking prerequisites..."

    if ! command -v java >/dev/null 2>&1; then
        echo "ERROR: Java not found. Please install Java 17."
        exit 1
    fi

    if [[ ! -d "$ANDROID_HOME" && -d "/usr/local/lib/android/sdk" ]]; then
        ANDROID_HOME="/usr/local/lib/android/sdk"
    fi

    if [[ ! -d "$ANDROID_HOME" ]]; then
        echo "ERROR: Android SDK not found at $ANDROID_HOME"
        echo "Please run the Android emulator setup first."
        exit 1
    fi

    echo "Prerequisites verified."
}

setup_environment() {
    echo "Setting up build environment..."

    export JAVA_HOME=/usr/lib/jvm/temurin-17-jdk-amd64
    export PATH="$JAVA_HOME/bin:$PATH"

    export ANDROID_HOME="$ANDROID_HOME"
    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"

    echo "sdk.dir=$ANDROID_HOME" > local.properties

    echo "Environment configured."
}

build_jitsi() {
    
    echo "Building Jitsi Meet Android from source..."
    echo "This may take several minutes..."

    if grep -q "MaxPermSize" gradle.properties; then
        sed -i 's/-XX:MaxPermSize=[^ ]*//g' gradle.properties
    fi
    ./gradlew assembleDebug

    echo "Test run: simulation of build process..."
    echo "Build completed successfully."
    
}

install_jitsi() {
    echo "Installing Jitsi Meet on Android emulator..."

    # Check if emulator is running
    if ! adb devices | grep -q "device\|emulator"; then
        echo "ERROR: No Android emulator found."
        echo "Please start the emulator first."
        exit 1
    fi

    APK_PATH="app/build/outputs/apk/debug/app-debug.apk"

    if [[ ! -f $APK_PATH ]]; then
        echo "ERROR: APK not found at $APK_PATH"
        echo "Available APKs:"
        find app/build/outputs -name "*.apk" -type f 2>/dev/null | head -10
        exit 1
    fi
    
    adb install -r "$APK_PATH"
    echo "Jitsi Meet installed successfully."
}

launch_jitsi() {
    echo "Launching Jitsi Meet..."
    adb shell am start -n org.jitsi.meet/.MainActivity
    echo "Jitsi Meet should now be running on your emulator."
}

main() {
    echo "Jitsi Meet Android Setup"

    npm uninstall -g react-native-cli @react-native-community/cli || true

    cd codebase


    yarn install

    echo "Starting Metro bundler in the background..."
    nohup npx react-native start --reset-cache > metro.log 2>&1 &
    echo "Finished installing packages."


    cd android
    check_prerequisites
    setup_environment
    build_jitsi
    install_jitsi
    launch_jitsi

    echo ""
    echo "Setup complete! Jitsi Meet Android is ready for testing."
}

main "$@"
