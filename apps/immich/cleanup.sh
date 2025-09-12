#!/usr/bin/env bash
set -euo pipefail

# Choose docker compose CLI
if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
else
  COMPOSE="docker-compose"
fi

# Ensure we're in the project directory
if [ ! -f "./docker-compose.yml" ]; then
  echo "❌ docker-compose.yml not found. Run this from the Immich project directory."
  exit 1
fi

echo "🧹 Cleaning up Immich environment (no prompt, keeping ./immich-data)..."

echo "[1/2] Shutting down containers & removing named volumes..."
$COMPOSE down -v --remove-orphans

echo "[2/2] Removing temporary secret files..."
rm -f .secrets .env.bak

echo "✅ Cleanup complete."
echo "Next: run '$COMPOSE up -d database' to re-init the DB from db/init/* on first run (if configured), then '$COMPOSE up -d'."
