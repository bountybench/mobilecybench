#!/bin/bash
set -e

BITWARDEN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BITWARDEN_PKG="com.x8bit.bitwarden.dev"
CACHED_APK="$BITWARDEN_DIR/bitwarden.apk"
BUILD_APK="$BITWARDEN_DIR/codebase/app/build/outputs/apk/fdroid/debug/com.x8bit.bitwarden.dev-fdroid.apk"

check_emulator_ready() {
  # Device visible to ADB?
  if ! adb devices | grep -w "device" | grep -v "List" >/dev/null; then
    echo "[ERROR] No Android emulator found. Please start the emulator first."
    exit 1
  else
    echo "[INFO] Emulator is running."
  fi

  echo "[INFO] Ensuring emulator is ready before install..."
  adb wait-for-device
}

# Install on emulator
install_bitwarden() {
    echo "[INFO] Installing Bitwarden on Android emulator..."
    
    # Check if cached APK exists, if not, check if build APK exists
    if [[ -f $CACHED_APK ]]; then
        echo "[INFO] Installing cached APK from $CACHED_APK..."
        adb install "$CACHED_APK" \
          || adb install -r -t -g "$CACHED_APK" \
          || (adb push "$CACHED_APK" /data/local/tmp/bitwarden.apk \
              && adb shell pm install -r -t -g /data/local/tmp/bitwarden.apk \
              && adb shell rm -f /data/local/tmp/bitwarden.apk)
    else
        if [[ -f $BUILD_APK ]]; then
            echo "[INFO] Installing build APK from $BUILD_APK..."
            adb install "$BUILD_APK" \
              || adb install -r -t -g "$BUILD_APK" \
              || (adb push "$BUILD_APK" /data/local/tmp/bitwarden.apk \
                  && adb shell pm install -r -t -g /data/local/tmp/bitwarden.apk \
                  && adb shell rm -f /data/local/tmp/bitwarden.apk)
        else
            echo "[ERROR] APK not found at $CACHED_APK or $BUILD_APK"
            exit 1
        fi
    fi
    
    # Verify package is installed
    if ! adb shell cmd package list packages | grep -q "$BITWARDEN_PKG"; then
        echo "[ERROR] Package $BITWARDEN_PKG not found after install."
        exit 1
    fi

    echo "[INFO] Bitwarden installed successfully."
}

# Launch Bitwarden directly
launch_bitwarden() {
    echo "[INFO] Launching Bitwarden..."
    
    # Launch Bitwarden using package name
    adb shell monkey -p $BITWARDEN_PKG -c android.intent.category.LAUNCHER 1
    
    # Verify launch by polling for the process ID
    echo "[INFO] Waiting for Bitwarden process to start..."
    for i in $(seq 1 15); do
        if adb shell pidof "$BITWARDEN_PKG" >/dev/null 2>&1; then
            echo "[INFO] Successfully launched Bitwarden (process found)!"
            return 0
        fi
        sleep 1
    done

    echo "[ERROR] Bitwarden may not have launched properly (process not found)."
    echo "[ERROR] Please check your emulator or device - Bitwarden should be installed."
    return 1
}

main() {
  echo "=== RUNNING setup_app.sh ==="
  check_emulator_ready

  echo "[INFO] Checking if Bitwarden app is installed on the emulator..."
  if adb shell pm list packages | grep -q "$BITWARDEN_PKG"; then
    echo "[INFO] Bitwarden app is already installed on the emulator."
  else
    echo "[INFO] Bitwarden app not found."
    install_bitwarden
  fi

  launch_bitwarden
  
  echo ""
  echo "=== FINISHED setup_app.sh ==="
}

main
