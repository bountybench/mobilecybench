#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

echo "Cleaning up OwnTracks environment..."

# Stop and remove Mosquitto MQTT broker container if it exists
if command -v docker &>/dev/null; then
    docker stop mosquitto 2>/dev/null || true
    docker rm mosquitto 2>/dev/null || true
fi

echo "Cleanup complete."

