#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

cd jitsi-docker/jitsi-latest

echo "Removing Docker containers..."
docker compose down -v

cd ../..

echo "Cleaning up docker volumes..."
docker volume prune -f

echo "Removing generated files..."
rm -f scores.json current_state.json agent.log prosody.hash

echo "Cleanup complete."
