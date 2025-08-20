#!/bin/bash
set -e

BITWARDEN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BITWARDEN_PKG="com.x8bit.bitwarden.dev"
CACHED_APK_PATH="$BITWARDEN_DIR/bitwarden.apk"
BUILD_APK_PATH="$BITWARDEN_DIR/codebase/app/build/outputs/apk/fdroid/debug/com.x8bit.bitwarden.dev-fdroid.apk"

check_emulator_ready() {
    # Check if emulator is running
    if ! adb devices | grep -w "device" | grep -v "List" >/dev/null; then
        echo "[ERROR] No Android emulator found. Please start the emulator first."
        exit 1
    else
        echo "[INFO] Emulator is running."
    fi
    
    echo "[INFO] Ensuring emulator is ready before install..."
    adb wait-for-device
    # Check for boot completion
    for i in $(seq 1 60); do
        boot=$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')
        if [ "$boot" = "1" ]; then break; fi
        sleep 1
    done
    # Check Package Manager is responsive
    for i in $(seq 1 30); do
        if adb shell cmd package list packages >/dev/null 2>&1; then break; fi
        sleep 1
    done
}

# Install on emulator
install_bitwarden() {
    echo "[INFO] Installing Bitwarden on Android emulator..."
    
    # Check if cached APK exists, if not, check if build APK exists
    if [[ -f $CACHED_APK_PATH ]]; then
        echo "[INFO] Installing cached APK from $CACHED_APK_PATH..."
        adb install "$CACHED_APK_PATH"
    else
        if [[ -f $BUILD_APK_PATH ]]; then
            echo "[INFO] Installing build APK from $BUILD_APK_PATH..."
            adb install "$BUILD_APK_PATH"
        else
            echo "[ERROR] APK not found at $CACHED_APK_PATH or $BUILD_APK_PATH"
            exit 1
        fi
    fi
    
    # Verify package is installed
    if ! adb shell cmd package list packages | grep -q "$BITWARDEN_PKG"; then
        echo "ERROR: Package $BITWARDEN_PKG not found after install."
        exit 1
    fi

    echo "Bitwarden installed successfully."
}

# Launch Bitwarden directly
launch_bitwarden() {
    echo "Launching Bitwarden..."
    
    # Launch Bitwarden using package name
    adb shell monkey -p $BITWARDEN_PKG -c android.intent.category.LAUNCHER 1
    
    # Verify launch with a short poll for foreground or running process
    launched=0
    for i in $(seq 1 15); do
        if adb shell dumpsys window | grep -q "mCurrentFocus.*$BITWARDEN_PKG"; then
            launched=1; break
        fi
        if adb shell pidof "$BITWARDEN_PKG" >/dev/null 2>&1; then
            launched=1; break
        fi
        sleep 1
    done
    if [ "$launched" = "1" ]; then
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

    check_emulator_ready

    echo "[INFO] Checking if Bitwarden app is installed on the emulator..."
    if adb shell pm list packages | grep -q "$BITWARDEN_PKG"; then
        echo "✅ Bitwarden app is already installed on the emulator."
    else
        echo "[INFO] Bitwarden app not found."
        install_bitwarden
    fi
    
    launch_bitwarden
    
    echo ""
    echo === FINISHED setup_app.sh ===
}

# Run main function
main 