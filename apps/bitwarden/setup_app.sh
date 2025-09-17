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

# Check if Vaultwarden server is running and start if needed
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
        docker compose up -d

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

# Create accounts using optimized database method with fallback
create_accounts_smart() {
    echo "[INFO] Creating user accounts using optimized method..."

    cd "$BITWARDEN_DIR"

    # Try the optimized database approach first
    echo "[INFO] Attempting optimized database account creation..."

    if python3 -c "
import sys
sys.path.append('$PROJECT_ROOT')
from apps.bitwarden.database_setup import setup_accounts_via_database
success, message = setup_accounts_via_database('accounts.json')
print(message)
exit(0 if success else 1)
" 2>/dev/null; then
        echo "[INFO] Optimized account creation completed successfully!"
        return 0
    else
        echo "[WARN] Optimized method failed. Falling back to UI automation..."

        # Fallback to original UI automation method
        python3 -c "
import sys
sys.path.append('$PROJECT_ROOT')
from utils.ui_utils import initialize_ui_automation
from apps.bitwarden.create_accounts import main, extract_secrets_from_db

d = initialize_ui_automation()
main(d)
extract_secrets_from_db()
"

        if [[ $? -eq 0 ]]; then
            echo "[INFO] UI automation fallback completed successfully!"
            return 0
        else
            echo "[ERROR] Both optimized and fallback methods failed."
            return 1
        fi
    fi
}

main() {
  echo "=== RUNNING OPTIMIZED setup_app.sh ==="
  echo "[INFO] This version uses direct database operations (no UI automation)"

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

  echo "[INFO] Creating accounts using direct database operations..."
  cd "$BITWARDEN_DIR"

  python3 -c "
import sys
sys.path.append('$PROJECT_ROOT')
from apps.bitwarden.create_accounts import main
main()
"

  if [[ $? -eq 0 ]]; then
    echo "[INFO] Account creation completed successfully!"
  else
    echo "[ERROR] Account creation failed."
    exit 1
  fi

  echo ""
  echo "=== FINISHED OPTIMIZED setup_app.sh ==="
}

main