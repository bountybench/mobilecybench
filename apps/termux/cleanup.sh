#!/bin/bash
set -e

# Check if minimal cleanup is requested
MINIMAL_CLEANUP=${1:-false}

if [ "$MINIMAL_CLEANUP" = "minimal" ]; then
    echo " Minimal cleanup (keeping app installed)..."
    
    # Only remove generated files
    echo "Removing generated files..."
    rm -f scores.json
    
    # Remove log files recursively 
    echo "Removing log files recursively..."
    find . -type f -name "*.log" -delete
    
    # Remove text files recursively 
    echo "Removing text files recursively..."
    find . -type f -name "*.txt" -delete
    
    echo ""
    echo "Minimal cleanup completed!"
    echo "Termux app remains installed"
    echo "Generated files removed"
    exit 0
fi

echo "Cleaning up Termux test environment..."

# Check if emulator is running
if ! adb devices | grep -q "emulator"; then
    echo "No emulator found, skipping app cleanup"
else
    echo "Cleaning up Termux app..."
    
    # Uninstall the main app
    if adb shell pm list packages | grep -q "com.termux"; then
        echo "Uninstalling Termux app..."
        adb uninstall com.termux
        echo "Termux app uninstalled"
    else
        echo "Termux app not installed"
    fi
    
    # Uninstall malicious test app from vulnerability scenarios
    if adb shell pm list packages | grep -q "com.test.malicious"; then
        echo "Uninstalling malicious test app..."
        adb uninstall com.test.malicious
        echo "Malicious test app uninstalled"
    fi
    
    # Clear device logs to remove any exploitation evidence
    echo "Clearing device logs..."
    adb logcat -c >/dev/null 2>&1 || true
fi


echo "Removing APKs..."
rm -f apk/termux-release.apk

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

# Remove generated APKs and build artifacts from perm_only_app
rm -f vuln_scenarios/vuln_scenario_0/malicious-perm-only.apk
rm -rf vuln_scenarios/vuln_scenario_0/perm_only_app/dist/
rm -rf vuln_scenarios/vuln_scenario_0/perm_only_app/build/
rm -f vuln_scenarios/vuln_scenario_0/perm_only_app/debug.keystore

# Remove log files recursively 
echo "Removing log files recursively..."
find . -type f -name "*.log" -delete

echo "Removing text files recursively..."
find . -type f -name "*.txt" -delete

echo "Cleanup completed successfully!"
