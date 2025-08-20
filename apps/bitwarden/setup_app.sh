#!/bin/bash
set -e

BITWARDEN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BITWARDEN_PKG="com.x8bit.bitwarden.dev"
CACHED_APK_PATH="$BITWARDEN_DIR/bitwarden.apk"
BUILD_APK_PATH="$BITWARDEN_DIR/codebase/app/build/outputs/apk/fdroid/debug/com.x8bit.bitwarden.dev-fdroid.apk"

# Install on emulator
install_bitwarden() {
    echo "Installing Bitwarden on Android emulator..."
    
    # Check if emulator is running
    if ! adb devices | grep -w "device" | grep -v "List" >/dev/null; then
        echo "ERROR: No Android emulator or device found."
        echo "Please start the emulator or connect a device first."
        exit 1
    fi
    
    # Check if cached APK exists, if not, check if build APK exists
    if [[ -f $CACHED_APK_PATH ]]; then
        adb install -r "$CACHED_APK_PATH"
    else
        if [[ -f $BUILD_APK_PATH ]]; then
            adb install -r "$BUILD_APK_PATH"
        else
            echo "ERROR: APK not found at $CACHED_APK_PATH or $BUILD_APK_PATH"
            exit 1
        fi
    fi
    
    echo "Bitwarden installed successfully."
}

# Launch Bitwarden directly
launch_bitwarden() {
    echo "Launching Bitwarden..."
    
    # Launch Bitwarden using package name
    adb shell monkey -p $BITWARDEN_PKG -c android.intent.category.LAUNCHER 1
    
    # Verify launch
    sleep 2
    if adb shell dumpsys window | grep -q "mCurrentFocus.*$BITWARDEN_PKG"; then
        echo "Successfully launched Bitwarden!"
        return 0
    else
        echo "Bitwarden may not have launched properly."
        echo "Please check your emulator or device - Bitwarden should be installed."
        return 1
    fi
}

# Main function
main() {
    echo "=== RUNNING setup_app.sh ==="
    
    install_bitwarden
    
    if launch_bitwarden; then
        echo "Bitwarden is now running and ready for testing!"
    else
        echo "Please manually launch Bitwarden from your emulator or device."
        echo "You can also try running: adb shell monkey -p $BITWARDEN_PKG -c android.intent.category.LAUNCHER 1"
    fi
    
    echo ""
    echo === FINISHED setup_app.sh ===
}

# Run main function
main 