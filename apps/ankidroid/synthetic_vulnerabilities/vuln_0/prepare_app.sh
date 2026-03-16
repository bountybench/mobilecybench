#!/bin/bash
set -e

LOG_PREFIX="[prepare_app]"
info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }

if ! adb devices | grep -q "device$"; then
    echo "$LOG_PREFIX[ERROR] No Android device/emulator detected" >&2
    exit 1
fi

# Launch AnkiDroid's launcher activity so the app initialises its collection
# and storage on first run. SharedDecksActivity requires this to be done before
# it can display its WebView (showedActivityFailedScreen guard in AnkiActivity).
info "Launching AnkiDroid to initialise app storage..."
adb shell monkey -p com.ichi2.anki -c android.intent.category.LAUNCHER 1 > /dev/null 2>&1
sleep 8

# Suppress the POST_NOTIFICATIONS permission dialog so it doesn't block UI
adb shell pm grant com.ichi2.anki android.permission.POST_NOTIFICATIONS 2>/dev/null || true

# Return to home screen
adb shell input keyevent KEYCODE_HOME
sleep 2

info "App initialised and ready"
