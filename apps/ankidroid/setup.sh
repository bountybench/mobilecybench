#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

adb start-server >/dev/null 2>&1 || true
adb wait-for-device

PKG="com.ichi2.anki"
adb uninstall "$PKG" >/dev/null 2>&1 || true
adb install -r -d app.apk

adb shell pm list packages | grep -q "$PKG" || { echo "Package not installed"; exit 1; }
echo "AnkiDroid installed successfully."