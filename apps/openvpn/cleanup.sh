#!/bin/bash

echo "Cleaning up OpenVPN testing environment..."

# Stop and remove Docker containers
echo "Stopping Docker containers..."
docker-compose down -v 2>/dev/null || echo "No compose services to stop"

# Remove Docker images
echo "Removing Docker images..."
docker rmi $(docker images -f "reference=openvpn_openvpn-server" -q) 2>/dev/null || echo "No OpenVPN images to remove"

# Clean up generated files
echo "Cleaning up generated files..."
rm -rf client-configs/ || true
rm -rf logs/ || true
rm -rf output/ || true
rm -rf secrets/ || true

# Clean up vulnerability test artifacts
rm -rf /tmp/vuln_scenario_* || true

# Remove Docker network (optional - may be used by other projects)
echo "Removing Docker network..."
docker network rm shared_net 2>/dev/null || echo "shared_net network not found or in use"

# Remove Docker volumes
echo "Removing Docker volumes..."
docker volume rm openvpn_openvpn-data 2>/dev/null || echo "No OpenVPN volume to remove"

# Uninstall app from emulator if connected
if adb devices 2>/dev/null | grep -q "emulator"; then
    echo "Uninstalling app from emulator..."
    adb uninstall de.blinkt.openvpn 2>/dev/null || echo "App not installed"
fi

echo "OpenVPN environment cleanup completed!"