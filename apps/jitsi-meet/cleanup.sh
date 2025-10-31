#!/bin/bash
set -e

cd jitsi-docker/jitsi-latest

echo "Removing Docker containers..."
docker compose down -v

cd ../..

echo "Cleaning up docker volumes..."
docker volume prune -f

echo "Removing generated files..."
rm -f scores.json current_state.json agent.log

echo "Cleanup complete."
