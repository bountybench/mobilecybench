#!/bin/bash

echo "Starting System UI watchdog..."
EMU_BOOTED=0
first_launcher=1
n=0
while [[ $EMU_BOOTED = 0 ]]; do
    CURRENT_FOCUS=$(adb shell dumpsys window 2>/dev/null | grep -i mCurrentFocus)
    echo "Current focus: ${CURRENT_FOCUS}"

    case $CURRENT_FOCUS in
    "Launcher")
        if [[ $first_launcher == 1 ]]; then
        echo "Launcher detected, waiting 10 sec in case of popups..."
        sleep 10
        first_launcher=0
        else
        echo "Launcher stable, boot complete."
        EMU_BOOTED=1
        fi
        ;;
    "Not Responding: com.android.systemui")
        echo "Dismissing System UI popup..."
        adb shell input keyevent KEYCODE_ENTER
        adb shell input keyevent KEYCODE_DPAD_DOWN
        adb shell input keyevent KEYCODE_ENTER
        first_launcher=1
        ;;
    "Not Responding: com.google.android.gms")
        echo "Dismissing GMS popup..."
        adb shell input keyevent KEYCODE_ENTER
        first_launcher=1
        ;;
    "Not Responding: system")
        echo "Dismissing Process System popup..."
        adb shell input keyevent KEYCODE_ENTER
        first_launcher=1
        ;;
    "ConversationListActivity")
        echo "Closing Messaging app..."
        adb shell input keyevent KEYCODE_ENTER
        first_launcher=1
        ;;
    *)
        n=$((n + 1))
        echo "Waiting for Android to boot ($n)..."
        sleep 10
        if [ $n -gt 60 ]; then
        echo "Timeout: Emulator failed to boot in 10 minutes."
        exit 2
        fi
        ;;
    esac
done