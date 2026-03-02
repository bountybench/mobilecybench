#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_PKG="org.openhab.habdroid"
PREFS_PATH="/data/data/${APP_PKG}/shared_prefs/log_activity_state.xml"

if ! command -v adb >/dev/null 2>&1; then
  echo "adb not found"
  exit 1
fi

adb wait-for-device >/dev/null 2>&1
adb root >/dev/null 2>&1 || true
adb wait-for-device >/dev/null 2>&1

if ! adb shell pm list packages | grep -q "^package:${APP_PKG}$"; then
  exit 0
fi

adb shell rm -f "$PREFS_PATH" >/dev/null 2>&1 || true
adb shell su 0 rm -f "$PREFS_PATH" >/dev/null 2>&1 || true
