#!/bin/bash
set -e

echo "Cleaning up SimpleLogin environment"
echo "==================="

DC="docker compose"

echo "Stopping all services..."
$DC down -v 2>/dev/null || true

echo "Removing any dangling containers..."
docker container prune -f 2>/dev/null || true

echo "Removing test result files..."
rm -f *_results.json 2>/dev/null || true

echo "Removing log files..."
find . -type f -name "*.log" -delete 2>/dev/null || true

echo "Uninstalling app..."
PACKAGE_NAME="io.simplelogin.android.fdroid"
if command -v adb >/dev/null 2>&1; then
    if adb shell pm list packages | grep -q "^package:$PACKAGE_NAME$"; then
        adb uninstall "$PACKAGE_NAME" || echo "Failed to uninstall $PACKAGE_NAME"
    else
        echo "Package $PACKAGE_NAME not installed, skipping uninstall"
    fi
else
    echo "adb not available; skipping app uninstallation from emulator"
fi

echo "Cleanup complete!"
echo "==================="