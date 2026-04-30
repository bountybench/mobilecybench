#!/bin/bash
set -e

echo "Removing scores..."
rm -f scores.json
rm -f generic_scores.json

echo "Uninstalling app..."
PACKAGE_NAME="com.nextcloud.talk2"
if adb devices 2>/dev/null | grep -q "device$"; then
    if adb shell pm list packages 2>/dev/null | grep -q "^package:$PACKAGE_NAME$"; then
        adb uninstall "$PACKAGE_NAME" || echo "Failed to uninstall $PACKAGE_NAME"
    else
        echo "Package $PACKAGE_NAME not installed, skipping uninstall"
    fi
    echo "Clearing ADB logs..."
    adb logcat -c || true
else
    echo "No emulator connected, skipping ADB cleanup"
fi

echo "Removing log files..."
rm -f *.log

echo "Removing synthetic vuln state..."
rm -f synthetic_vulnerabilities/vuln_1/exploit_files/runtime_state.json
rm -f /tmp/nextcloud-talk-synth-vuln_1.json

echo "Taking down containers..."
docker compose down -v 2>/dev/null || true

echo "Cleanup complete"
