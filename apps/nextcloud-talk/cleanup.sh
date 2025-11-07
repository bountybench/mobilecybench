#!/bin/bash
set -e

echo "Removing scores..."
rm -f scores.json
rm -f generic_scores.json

echo "Uninstalling app..."
PACKAGE_NAME="com.nextcloud.talk2"
if adb shell pm list packages | grep -q "^package:$PACKAGE_NAME$"; then
    adb uninstall "$PACKAGE_NAME" || echo "Failed to uninstall $PACKAGE_NAME"
else
    echo "Package $PACKAGE_NAME not installed, skipping uninstall"
fi

echo "Clearing ADB logs..."
adb logcat -c || true

echo "Removing log files..."
rm -f *.log

echo "Taking down containers..."
docker compose down -v

echo "Cleanup complete"
