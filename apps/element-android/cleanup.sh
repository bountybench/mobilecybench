#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Cleaning up Element Android environment..."

# Stop and remove Docker containers
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    echo "Stopping Docker containers..."
    docker compose down -v --remove-orphans
else
    echo "docker compose not available; skipping."
fi

# Reset synapse data directory
if [ -d "synapse-data" ]; then
    echo "Resetting synapse data..."
    rm -rf synapse-data
    mkdir -p synapse-data
fi

# Uninstall Element app
if command -v adb >/dev/null 2>&1 && [ -f "metadata.json" ] && command -v jq >/dev/null 2>&1; then
    PACKAGE_NAME=$(jq -r '.package_name // empty' metadata.json)
    if [ -n "$PACKAGE_NAME" ] && adb shell pm list packages 2>/dev/null | grep -q "^package:$PACKAGE_NAME$"; then
        echo "Uninstalling $PACKAGE_NAME"
        adb uninstall "$PACKAGE_NAME" 2>/dev/null || true
    fi
fi

# Uninstall malicious app
if command -v adb >/dev/null 2>&1; then
    PKG="com.example.elementexploit"
    if adb shell pm list packages 2>/dev/null | grep -q "^package:$PKG$"; then
        echo "Uninstalling $PKG"
        adb uninstall "$PKG" 2>/dev/null || true
    fi

    # Clean up test artifacts from device
    echo "Cleaning test artifacts..."
    adb shell rm -f /sdcard/*.stolen 2>/dev/null || true
    adb shell rm -f /sdcard/element*.txt 2>/dev/null || true
fi

# Clean up test logs and evidence files
echo "Cleaning local test artifacts..."
rm -f exploit_evidence.txt 2>/dev/null || true
rm -f vuln_scenarios/*/fake_agent_log.log 2>/dev/null || true
rm -f /tmp/element*.stolen 2>/dev/null || true
rm -f /tmp/element_stolen_data.txt 2>/dev/null || true

# Kill any lingering background processes
pkill -f "rogue_server.py" 2>/dev/null || true

echo "Cleanup complete!"
