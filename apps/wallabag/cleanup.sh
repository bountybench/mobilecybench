#!/bin/bash
set -e

echo "Cleaning up Wallabag testing environment..."

# Stop and remove Docker containers
echo "Stopping Docker containers..."
docker-compose down -v 2>/dev/null || echo "No compose services to stop"
docker stop wallabag-db-1 2>/dev/null || echo "No wallabag-db-1 container to stop"
docker rm wallabag-db-1 2>/dev/null || echo "No wallabag-db-1 container to remove"

# Clean up generated files
echo "Cleaning up generated files..."
rm -f *.apk || true
rm -f scores.json || true
rm -f *.log || true
rm -f init-db.sql || true
rm -rf downloads/ || true
rm -rf logs/ || true
rm -rf output/ || true

# Clean up vulnerability test artifacts
find . -type f -name "fake_agent_log.log" -delete
rm -rf /tmp/vuln_scenario_* || true

echo "Wallabag environment cleanup completed!"
