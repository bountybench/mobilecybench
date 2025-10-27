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
