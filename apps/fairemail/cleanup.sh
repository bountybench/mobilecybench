#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Cleaning up FairEmail test environment..."

# Check if emulator is running
if ! adb devices | grep -q "emulator"; then
    echo "No emulator found, skipping app cleanup"
else
    echo "Cleaning up FairEmail app..."
    
    # Uninstall the main app
    if adb shell pm list packages | grep -q "eu.faircode.email"; then
        echo "Uninstalling FairEmail app..."
        adb uninstall eu.faircode.email
        echo "FairEmail app uninstalled"
    else
        echo "FairEmail app not installed"
    fi
    
    # Clear device logs to remove any exploitation evidence
    echo "Clearing device logs..."
    adb logcat -c >/dev/null 2>&1 || true
fi

echo "Removing APKs..."
rm -f "$SCRIPT_DIR/apk"/*.apk

# Clean build artifacts in codebase
if [ -d "$SCRIPT_DIR/codebase" ]; then
    echo "Cleaning build artifacts..."
    cd "$SCRIPT_DIR/codebase"
    ./gradlew clean 2>/dev/null || echo "Gradle clean failed (may not be built yet)"
    cd "$SCRIPT_DIR"
fi

# Remove generated files
echo "Removing generated files..."
rm -f "$SCRIPT_DIR/scores.json"

# Remove vulnerability scenario evidence files
echo "Removing vulnerability scenario evidence..."
rm -f "$SCRIPT_DIR/exploit_evidence.txt"
rm -f "$SCRIPT_DIR/dos_evidence.txt"
rm -f "$SCRIPT_DIR/fake_agent_log.log"
rm -f "$SCRIPT_DIR"/*.stolen
find "$SCRIPT_DIR" -name "*.stolen" -delete

# Remove log files recursively 
echo "Removing log files recursively..."
find "$SCRIPT_DIR" -type f -name "*.log" -delete

echo "Removing text files recursively..."
find "$SCRIPT_DIR" -type f -name "*.txt" -delete

echo "Cleanup completed successfully!"

