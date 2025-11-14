#!/bin/bash
set -e

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
rm -f apk/*.apk

# Clean build artifacts in codebase
if [ -d "codebase" ]; then
    echo "Cleaning build artifacts..."
    cd codebase
    ./gradlew clean 2>/dev/null || echo "Gradle clean failed (may not be built yet)"
    cd ..
fi

# Remove generated files
echo "Removing generated files..."
rm -f scores.json

# Remove vulnerability scenario evidence files
echo "Removing vulnerability scenario evidence..."
rm -f exploit_evidence.txt
rm -f dos_evidence.txt
rm -f fake_agent_log.log
rm -f *.stolen
find . -name "*.stolen" -delete

# Remove log files recursively 
echo "Removing log files recursively..."
find . -type f -name "*.log" -delete

echo "Removing text files recursively..."
find . -type f -name "*.txt" -delete

echo "Cleanup completed successfully!"

