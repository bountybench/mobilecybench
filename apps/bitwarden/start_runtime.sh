#!/bin/bash
set -e

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$APP_DIR/../../" && pwd)"

echo "=== Starting Bitwarden Runtime ==="

# 1. Orchestrate backend containers
echo "[INFO] Orchestrating backend containers..."
docker compose -f "$APP_DIR/docker-compose.yml" up -d --build --wait

# 2. Wait for Vaultwarden to be healthy (the --wait flag in docker compose up handles healthchecks if defined, 
# but vaultwarden-db healthcheck might be slower than the app start)
echo "[INFO] Waiting for Vaultwarden to be ready on http://localhost:8000..."
until curl -sf http://localhost:8000/alive > /dev/null; do
  echo "Still waiting for Vaultwarden..."
  sleep 5
done
echo "[INFO] Vaultwarden is healthy."

# 3. Handle database seeding/account creation
echo "[INFO] Seeding database and creating accounts..."
# We use the existing create_accounts.py but ensure the environment is set up
export PYTHONPATH=$PYTHONPATH:$ROOT_DIR
cd "$ROOT_DIR"
python3 -m apps.bitwarden.create_accounts

echo "=== Bitwarden Runtime Started ==="
