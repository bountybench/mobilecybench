#!/bin/bash
set -e

echo "Cleaning up Wallabag testing environment..."

# Stop and remove Docker containers
echo "Stopping Docker containers..."
docker-compose down -v 2>/dev/null || echo "No compose services to stop"
docker stop wallabag-server 2>/dev/null || echo "No wallabag-server container to stop"
docker rm wallabag-server 2>/dev/null || echo "No wallabag-server container to remove"
docker stop wallabag-db 2>/dev/null || echo "No wallabag-db container to stop"
docker rm wallabag-db 2>/dev/null || echo "No wallabag-db container to remove"

# Remove Docker images (if custom images were built)
echo "Removing Docker images..."
docker rmi wallabag-server:latest 2>/dev/null || echo "No Wallabag server image to remove"

# Clean up generated files
echo "Cleaning up generated files..."
rm -f *.apk || true
rm -f secrets.json || true
rm -f scores.json || true
rm -f *.log || true
rm -f init-db.sql || true
rm -rf downloads/ || true
rm -rf logs/ || true
rm -rf output/ || true

# Clean up vulnerability test artifacts
find . -type f -name "fake_agent_log.log" -delete
rm -rf /tmp/vuln_scenario_* || true

# Remove Docker networks (optional)
echo "Removing Docker network..."
docker network rm shared_net 2>/dev/null || echo "shared_net network not found or in use"

# Remove Docker volumes (only if you created specific named ones)
echo "Removing Docker volumes..."
docker volume rm wallabag-data 2>/dev/null || echo "No Wallabag volume to remove"

# Uninstall app from emulator if connected
export ANDROID_HOME="${ANDROID_HOME:-$HOME/.android-sdk}"
export PATH="$ANDROID_HOME/platform-tools:$PATH"
if command -v adb >/dev/null 2>&1 && adb devices 2>/dev/null | grep -q "emulator"; then
    echo "Uninstalling app from emulator..."
    adb uninstall fr.gaulupeau.apps.InThePoche 2>/dev/null || echo "App not installed"
fi

echo "Wallabag environment cleanup completed!"
