#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Cleaning up Element Android environment..."

# Stop and remove Docker resources for this project
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    echo "Stopping Docker containers..."
    docker compose down -v --remove-orphans
else
    echo "docker compose not available; skipping container shutdown."
fi

# Reset synapse data directory
if [ -d "synapse-data" ]; then
    echo "Resetting synapse data directory..."
    rm -rf synapse-data
    mkdir -p synapse-data
fi

# Uninstall the app if it's installed
if command -v adb >/dev/null 2>&1 && [ -f "metadata.json" ] && command -v jq >/dev/null 2>&1; then
    PACKAGE_NAME=$(jq -r '.package_name // empty' metadata.json)
    if [ -n "$PACKAGE_NAME" ]; then
        # Check if package is installed
        if adb shell pm list packages 2>/dev/null | grep -q "^package:$PACKAGE_NAME$"; then
            echo "Uninstalling package: $PACKAGE_NAME"
            adb uninstall "$PACKAGE_NAME"
        fi
    fi
fi

# Uninstall malicious exploit apps if installed (from vulnerability scenarios)
if command -v adb >/dev/null 2>&1; then
    # Uninstall elementexploit app (vuln_scenario_0/1)
    MALICIOUS_PKG="com.example.elementexploit"
    if adb shell pm list packages 2>/dev/null | grep -q "^package:$MALICIOUS_PKG$"; then
        echo "Uninstalling malicious exploit app: $MALICIOUS_PKG"
        adb uninstall "$MALICIOUS_PKG"
    fi

    # Uninstall elementexfiltrate app (vuln_scenario_2)
    EXFILTRATE_PKG="com.example.elementexfiltrate"
    if adb shell pm list packages 2>/dev/null | grep -q "^package:$EXFILTRATE_PKG$"; then
        echo "Uninstalling file exfiltration app: $EXFILTRATE_PKG"
        adb uninstall "$EXFILTRATE_PKG"
    fi
fi

# Note: Do NOT remove the apk file as per requirements

echo "Element Android cleanup complete!"
