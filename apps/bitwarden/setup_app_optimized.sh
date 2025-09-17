#!/bin/bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../" && pwd)"
UTILS_DIR="$PROJECT_ROOT/utils"
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

  # Run the readiness util script to ensure the emulator is ready
  "$UTILS_DIR/android_emulator_ready.sh"
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

# Check if Vaultwarden server is running
check_vaultwarden_server() {
    echo "[INFO] Checking if Vaultwarden server is running..."

    # Check if docker containers are running
    if ! docker ps | grep -q "vaultwarden"; then
        echo "[INFO] Starting Vaultwarden server..."
        cd "$BITWARDEN_DIR"

        # Create .env file if it doesn't exist
        if [[ ! -f .env ]]; then
            echo "[INFO] Creating .env file..."
            cat > .env << EOF
DB_USER=bitwarden
DB_PASSWORD=super_strong_password
DB_NAME=vaultwarden
EOF
        fi

        # Start the docker containers
        docker-compose up -d

        # Wait for services to be healthy
        echo "[INFO] Waiting for Vaultwarden server to be ready..."
        for i in $(seq 1 60); do
            if curl -s http://localhost:8000/alive > /dev/null 2>&1; then
                echo "[INFO] Vaultwarden server is ready!"
                break
            fi
            if [[ $i -eq 60 ]]; then
                echo "[ERROR] Vaultwarden server failed to start within 60 seconds."
                exit 1
            fi
            sleep 1
        done
    else
        echo "[INFO] Vaultwarden server is already running."
    fi
}

# Create accounts using optimized method
create_accounts_optimized() {
    echo "[INFO] Creating user accounts using optimized database method..."

    cd "$BITWARDEN_DIR"

    # Use Python to create accounts directly in database
    python3 -c "
import sys
sys.path.append('$PROJECT_ROOT')
from apps.bitwarden.create_accounts_optimized import create_accounts_optimized
create_accounts_optimized('accounts.json')
"

    if [[ $? -eq 0 ]]; then
        echo "[INFO] User accounts created successfully via database!"
    else
        echo "[ERROR] Failed to create user accounts via database."
        echo "[INFO] Falling back to UI automation method..."

        # Fallback to original UI automation method
        python3 -c "
import sys
sys.path.append('$PROJECT_ROOT')
from utils.ui_utils import initialize_ui_automation
from apps.bitwarden.create_accounts import main

d = initialize_ui_automation()
main(d)
"
    fi
}

main() {
    echo "=== RUNNING OPTIMIZED setup_app.sh ==="

    check_emulator_ready
    check_vaultwarden_server

    echo "[INFO] Checking if Bitwarden app is installed on the emulator..."
    if adb shell pm list packages | grep -q "$BITWARDEN_PKG"; then
        echo "[INFO] Bitwarden app is already installed on the emulator."
    else
        echo "[INFO] Bitwarden app not found."
        install_bitwarden
    fi

    launch_bitwarden

    # Give the app a moment to fully initialize
    sleep 3

    create_accounts_optimized

    echo ""
    echo "=== FINISHED OPTIMIZED setup_app.sh ==="
}

main