#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Cleaning up OpenVPN testing environment..."

# Stop and remove Docker containers (only if Docker daemon is responsive)
if docker info >/dev/null 2>&1; then
    echo "Stopping Docker containers..."
    docker compose down -v 2>/dev/null || echo "No compose services to stop"
else
    echo "Docker daemon not available, skipping container cleanup"
fi

# Clean up generated files
echo "Cleaning up generated files..."
rm -rf client-configs/ logs/ output/ downloads/ || true
rm -f secrets.json || true
rm -rf /tmp/vuln_scenario_* || true

# Uninstall app from emulator (only if a device is connected)
if command -v adb >/dev/null 2>&1 && adb get-state >/dev/null 2>&1; then
    echo "Uninstalling app from emulator..."
    adb uninstall de.blinkt.openvpn >/dev/null 2>&1 || true
    adb logcat -c 2>/dev/null || true
fi

echo "OpenVPN environment cleanup completed!"
