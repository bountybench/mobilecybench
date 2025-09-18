#!/bin/bash
set -e

echo "Removing scores..."
rm -f scores.json

echo "Clearing ADB logs..."
adb logcat -c

echo "Removing log files..."
rm -f fake_agent_log.log
rm -f *.log

echo "Taking down containers..."
docker compose down -v --remove-orphans

echo "Removing Docker networks..."
docker network rm jellyfin_shared_net 2>/dev/null || echo "Network already removed or doesn't exist"

echo "Pruning unused Docker resources..."
docker system prune -f --volumes

echo "Cleanup complete"
