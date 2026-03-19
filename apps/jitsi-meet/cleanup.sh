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

echo "Removing python attacker server if it exists"
if [ -f /tmp/attacker_server.pid ]; then
    kill $(cat /tmp/attacker_server.pid) 2>/dev/null || true
    rm /tmp/attacker_server.pid
    echo "Attacker server stopped"
else
    # Fallback: kill by port in case pid file is missing
    fuser -k 5000/tcp 2>/dev/null || true
fi

echo "Cleanup complete."
