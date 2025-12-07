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

# Note: Do NOT remove the apk file as per requirements

echo "Element Android cleanup complete!"

# Uninstall the app if it's installed
# Get package name from metadata.json if available
if command -v adb >/dev/null 2>&1 && adb devices | grep -q "device$"; then
    if [ -f "metadata.json" ] && command -v jq >/dev/null 2>&1; then
        PACKAGE_NAME=$(jq -r '.package_name // empty' metadata.json)
        if [ -n "$PACKAGE_NAME" ]; then
            if adb shell pm list packages | grep -q "^package:$PACKAGE_NAME$"; then
                echo "Uninstalling package: $PACKAGE_NAME"
                adb uninstall "$PACKAGE_NAME" || echo "Warning: Failed to uninstall $PACKAGE_NAME"
            fi
        fi
    fi
fi
