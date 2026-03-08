#!/bin/bash
set -e

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$APP_DIR/../../" && pwd)"
PKG_NAME="com.x8bit.bitwarden.dev"

echo "=== Setting up Bitwarden Environment ==="

# 1. Build the APK
echo "[INFO] Building Bitwarden APK..."
"$APP_DIR/build.sh"

# 2. Start the backend runtime
echo "[INFO] Starting Bitwarden backend services..."
"$APP_DIR/start_runtime.sh"

# 3. Install APK on emulator (required for UI tests)
# We use the standardized helper if available, or stay consistent with current setup_app.sh logic
echo "[INFO] Installing APK on emulator..."
# Locate the APK - build.sh or build_apk.sh usually puts it in codebase/... or app root
APK_PATH=$(find "$APP_DIR/codebase" -name "*.apk" | head -n 1)
if [ -z "$APK_PATH" ] && [ -f "$APP_DIR/bitwarden.apk" ]; then
    APK_PATH="$APP_DIR/bitwarden.apk"
fi

if [ -n "$APK_PATH" ]; then
    echo "[INFO] Found APK at $APK_PATH. Installing..."
    adb install -r -t -g "$APK_PATH"
else
    echo "[ERROR] No APK found to install. Build might have failed."
    exit 1
fi

echo "=== Bitwarden Setup Complete ==="
