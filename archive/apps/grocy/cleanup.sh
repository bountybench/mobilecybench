#!/bin/bash
set -e

# Check if emulator is running
if ! adb devices 2>/dev/null | grep -q "emulator"; then
    echo "No emulator found, skipping app cleanup"
else
    echo "Cleaning up Grocy app..."

    # Uninstall the app
    if adb shell pm list packages 2>/dev/null | grep -q "xyz.zedler.patrick.grocy"; then
        echo "Uninstalling Grocy app..."
        adb uninstall xyz.zedler.patrick.grocy || true
        echo "Grocy app uninstalled"
    else
        echo "Grocy app not installed"
    fi
fi

echo "Removing log files recursively..."
find . -type f -name "*.log" -delete 2>/dev/null || true

echo "Removing txt files recursively..."
find . -type f -name "*.txt" -delete 2>/dev/null || true

echo "Taking down containers..."
# Support both docker-compose (v1) and docker compose (v2 plugin)
if command -v docker-compose >/dev/null 2>&1; then
    docker-compose down
else
    docker compose down
fi

echo "Cleanup complete."
