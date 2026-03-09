#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../../" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"

# Resolve APK path using standard helper (supports --apk <path> override)
# App name used for lookup is "bitwarden"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "bitwarden" "$@")
cd "$SCRIPT_DIR"

echo "=== Starting Bitwarden Runtime ==="

# 1. Orchestrate backend containers (Vaultwarden + Postgres)
echo "[INFO] Orchestrating backend containers..."
docker compose -f "$SCRIPT_DIR/docker-compose.yml" up -d --build --wait

# 2. Wait for Vaultwarden to be healthy (the --wait flag handles this if healthchecks are defined)
# But we'll add an explicit check to be sure
echo "[INFO] Waiting for Vaultwarden to be ready on http://localhost:8000..."
until curl -sf http://localhost:8000/alive > /dev/null; do
  echo "Still waiting for Vaultwarden..."
  sleep 5
done
echo "[INFO] Vaultwarden is healthy."

# 3. Install the APK (standardized helper)
echo "[INFO] Installing Bitwarden APK..."
adb_install_apk "$APK_PATH"

# 4. Handle database seeding and account creation
# Note: we use UI automation to create accounts via the app
# This guarantees correct encryption schemas in the DB.
echo "[INFO] Seeding database and creating accounts via UI automation..."
export PYTHONPATH="${ROOT_DIR}:${PYTHONPATH:-}"
cd "$ROOT_DIR"
python3 -m apps.bitwarden.create_accounts

echo "=== Bitwarden Runtime Started ==="
