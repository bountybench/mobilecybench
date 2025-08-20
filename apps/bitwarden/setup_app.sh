#!/bin/bash
set -e

BITWARDEN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BITWARDEN_PKG="com.x8bit.bitwarden.dev"
CACHED_APK_PATH="$BITWARDEN_DIR/bitwarden.apk"
BUILD_APK_PATH="$BITWARDEN_DIR/codebase/app/build/outputs/apk/fdroid/debug/com.x8bit.bitwarden.dev-fdroid.apk"

# Increase install timeout to avoid early failures under CI load
export ADB_INSTALL_TIMEOUT=${ADB_INSTALL_TIMEOUT:-180}

# Wait for emulator boot completion and Package Manager readiness
wait_for_device_ready() {
    echo "[INFO] Waiting for device to be ready..."
    adb wait-for-device
    # Wait for sys.boot_completed
    for i in $(seq 1 120); do
        boot=$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')
        if [ "$boot" = "1" ]; then
            break
        fi
        sleep 1
    done
    # Wait for Package Manager service to respond
    for i in $(seq 1 60); do
        if adb shell cmd package list packages >/dev/null 2>&1; then
            echo "[INFO] Package Manager is responsive."
            return 0
        fi
        sleep 2
    done
    echo "[WARN] Package Manager did not respond in time; proceeding but installs may fail."
}

# Retry wrapper for adb install to handle transient PM/ADB issues (e.g., Broken pipe)
adb_install_with_retry() {
    local apk_path="$1"
    local attempts=3
    local delay=5
    for attempt in $(seq 1 $attempts); do
        echo "[INFO] adb install attempt $attempt/$attempts: $apk_path"
        set +e
        adb install -r -d -t "$apk_path"
        status=$?
        set -e
        if [ $status -eq 0 ]; then
            echo "[INFO] Install succeeded on attempt $attempt"
            return 0
        fi
        echo "[WARN] Install failed (exit $status). Collecting brief diagnostics and retrying..."
        adb shell getprop sys.boot_completed 2>/dev/null | sed 's/^/[diag] boot_completed=/' || true
        adb shell pidof system_server 2>/dev/null | sed 's/^/[diag] system_server pid=/' || true
        adb shell df -h /data 2>/dev/null | sed 's/^/[diag] /' || true
        wait_for_device_ready
        sleep "$delay"
    done
    echo "[ERROR] adb install failed after $attempts attempts."
    return 1
}

# Install on emulator
install_bitwarden() {
    echo "Installing Bitwarden on Android emulator..."
    
    # Check if emulator is running
    if ! adb devices | grep -w "device" | grep -v "List" >/dev/null; then
        echo "ERROR: No Android emulator or device found."
        echo "Please start the emulator or connect a device first."
        exit 1
    fi
    
    wait_for_device_ready
    
    # Check if cached APK exists, if not, check if build APK exists
    if [[ -f $CACHED_APK_PATH ]]; then
        adb_install_with_retry "$CACHED_APK_PATH"
    else
        if [[ -f $BUILD_APK_PATH ]]; then
            adb_install_with_retry "$BUILD_APK_PATH"
        else
            echo "ERROR: APK not found at $CACHED_APK_PATH or $BUILD_APK_PATH"
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