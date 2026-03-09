#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Cleaning up OpenVPN testing environment..."

# Stop and remove Docker containers (preserves images and network for next phase)
echo "Stopping Docker containers..."
docker compose down -v 2>/dev/null || echo "No compose services to stop"

# Clean up generated files
echo "Cleaning up generated files..."
rm -rf client-configs/ logs/ output/ downloads/ || true
rm -rf /tmp/vuln_scenario_* || true

# Remove Docker network (optional - may be used by other projects)
echo "Removing Docker network..."
docker network rm shared_net 2>/dev/null || echo "shared_net network not found or in use"

# Uninstall app from emulator if connected
export ANDROID_HOME="${ANDROID_HOME:-$HOME/.android-sdk}"
export PATH="$ANDROID_HOME/platform-tools:$PATH"
if command -v adb >/dev/null 2>&1 && adb devices 2>/dev/null | grep -q "emulator"; then
    echo "Uninstalling app from emulator..."
    adb uninstall de.blinkt.openvpn 2>/dev/null || echo "App not installed"
fi

# Clear ADB logs
adb logcat -c 2>/dev/null || true

echo "OpenVPN environment cleanup completed!"
