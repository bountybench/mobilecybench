#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

adb start-server >/dev/null 2>&1 || true
adb wait-for-device

PKG="org.owntracks.android.debug"
adb uninstall "$PKG" >/dev/null 2>&1 || true
adb install -r -d apk/owntracks.apk

adb shell pm list packages | grep -q "$PKG" || { echo "Package not installed"; exit 1; }
echo "OwnTracks installed successfully."

