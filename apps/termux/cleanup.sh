#!/bin/bash
set -e

echo "Cleaning up Termux test environment..."

if ! adb devices | grep -q "emulator"; then
    echo "No emulator found, skipping app cleanup"
else
    if adb shell pm list packages | grep -q "com.termux"; then
        echo "Uninstalling Termux app..."
        adb uninstall com.termux
    fi

    echo "Clearing device logs..."
    adb logcat -c >/dev/null 2>&1 || true
fi

if [ -d "codebase" ]; then
    echo "Cleaning build artifacts..."
    cd codebase
    ./gradlew clean >/dev/null 2>&1 || true
    cd ..
fi

echo "Removing generated files..."
rm -f scores.json exploit_evidence.txt
find . -name "*.stolen" -delete
find . -type f -name "*.log" -delete
find . -type f -name "*.txt" -not -name "secrets.json" -delete

echo "Cleanup completed successfully!"
