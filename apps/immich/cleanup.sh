#!/bin/bash
echo "🧹 Cleaning up Immich environment..."
echo "[1/2] Shutting down Docker containers..."
docker-compose down -v --remove-orphans
echo "[2/2] Removing temporary secret files..."
rm -f .secrets
rm -f .env.bak
echo "✅ Cleanup complete."