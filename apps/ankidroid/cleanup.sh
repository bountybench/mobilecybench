#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[INFO] Cleaning up AnkiDroid..."

# Uninstall the app
adb uninstall com.ichi2.anki 2>/dev/null || echo "App not installed, skipping uninstall"

# Stop and remove containers
cd "$SCRIPT_DIR"
if [ -f docker-compose.yml ]; then
    docker-compose down 2>/dev/null || echo "Containers not running"
fi

echo "[INFO] Cleanup complete"