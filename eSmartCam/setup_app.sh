#!/usr/bin/env bash
# Minimal setup script for eSmartCam (versionCode 72)
# 1. Downloads the APK if missing
# 2. Installs (or updates) it on the connected emulator/device
# 3. Launches the main launcher activity via monkey

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APK_URL="https://d.apkpure.com/b/APK/com.cn.dq.ipc?versionCode=72&nc=arm64-v8a%2Carmeabi%2Carmeabi-v7a%2Cx86%2Cx86_64&sv=23"
APK_FILE="$SCRIPT_DIR/eSmartCam_2.1.5_APKPure.apk"
PACKAGE_NAME="com.cn.dq.ipc"

# Locate adb (ANDROID_HOME, default path, or PATH)
if [[ -n "${ANDROID_HOME:-}" && -x "$ANDROID_HOME/platform-tools/adb" ]]; then
  ADB="$ANDROID_HOME/platform-tools/adb"
else
  ADB="${HOME}/.android-sdk/platform-tools/adb"
  [[ -x "$ADB" ]] || ADB=$(command -v adb || true)
fi

[[ -x "$ADB" ]] || { echo "adb not found. Install Android platform-tools or set ANDROID_HOME." >&2; exit 1; }

# Wait for device/emulator
"$ADB" wait-for-device

echo "[+] Device ready"

# Download APK if not present
if [[ ! -f "$APK_FILE" ]]; then
  echo "[+] Downloading eSmartCam APK …"
  UA="Mozilla/5.0"
  curl -L --fail --retry 2 -H "User-Agent: $UA" -o "$APK_FILE" "$APK_URL" || {
    echo "Download failed. You can manually place the APK at $APK_FILE and rerun." >&2
    exit 1
  }
fi

echo "[+] Installing/Updating APK …"
"$ADB" install -r "$APK_FILE" || true

echo "[+] Launching $PACKAGE_NAME …"
"$ADB" shell monkey -p "$PACKAGE_NAME" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 &

echo "[✔] eSmartCam should now be running."
