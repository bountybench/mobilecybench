#!/bin/bash
set -e

cd jitsi-docker/jitsi-latest

echo "Removing Docker containers..."
docker compose down -v

cd ../..

echo "Cleaning up config directories..."
sudo rm -rf ~/.jitsi-meet-cfg

echo "Removing generated files..."
sudo rm -f scores.json current_state.json agent.log

echo "Cleanup complete."
