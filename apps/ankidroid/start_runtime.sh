#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "ankidroid" "$@")

cd "$SCRIPT_DIR"

adb start-server >/dev/null 2>&1 || true
adb wait-for-device

PKG="com.ichi2.anki"
adb uninstall "$PKG" >/dev/null 2>&1 || true
adb install -r -d "$APK_PATH"

adb shell pm list packages | grep -q "$PKG" || { echo "Package not installed"; exit 1; }
echo "AnkiDroid installed successfully."
