#!/usr/bin/env bash
set -euo pipefail

# Use docker compose if available; fall back to docker-compose
if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
else
  COMPOSE="docker-compose"
fi

# Safety check: ensure we're in the repo that has the compose file
if [ ! -f "./docker-compose.yml" ]; then
  echo "❌ docker-compose.yml not found in current directory."
  echo "   Run this script from apps/immich (where your compose file lives)."
  exit 1
fi

# Flags
AUTO_YES="${1:-}"
if [ "$AUTO_YES" != "-y" ] && [ "$AUTO_YES" != "--yes" ]; then
  echo "⚠️  This will STOP containers, DELETE Postgres/Redis volumes,"
  echo "   and REMOVE ./immich-data (uploads). Data loss is permanent."
  read -r -p "Proceed? [y/N] " REPLY
  [[ "$REPLY" == "y" || "$REPLY" == "Y" ]] || { echo "Aborted."; exit 1; }
fi

echo "🧹 Cleaning up Immich environment..."

echo "[1/4] Shutting down containers & removing named volumes..."
$COMPOSE down -v --remove-orphans

echo "[2/4] Removing bind-mounted uploads (./immich-data)…"
# Remove uploads directory but keep the parent in git
if [ -d "./immich-data" ]; then
  rm -rf ./immich-data
fi
mkdir -p ./immich-data   # recreate empty for next run

echo "[3/4] Removing any legacy bind-mounted DB dirs (if they exist)…"
rm -rf ./immich-data/db ./postgres-data ./db/data || true

echo "[4/4] Removing temporary secret files…"
rm -f .secrets .env.bak

echo "✅ Cleanup complete."
echo "Next: `docker compose up -d database` will re-init the DB from db/init/* on first run."
