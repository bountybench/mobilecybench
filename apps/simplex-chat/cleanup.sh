#!/bin/bash

# cleanup.sh
# Responsible for cleaning up Docker containers and files
# Does not remove .apk files

set -e

echo "Starting cleanup..."

# Stop and remove Docker containers
echo "Stopping and removing Docker containers..."
docker-compose down -v 2>/dev/null || true
docker stop $(docker ps -aq) 2>/dev/null || true
docker rm $(docker ps -aq) 2>/dev/null || true

# Remove temporary files but preserve .apk files
echo "Cleaning up temporary files (preserving .apk files)..."
find . -type f -name "*.tmp" -delete 2>/dev/null || true
find . -type f -name "*.log" -delete 2>/dev/null || true
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true

echo "Cleanup completed!"
