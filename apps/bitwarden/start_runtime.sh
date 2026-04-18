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

HOST_ALIVE_TIMEOUT=${HOST_ALIVE_TIMEOUT:-180}

dump_runtime_diagnostics() {
  echo "[ERROR] Bitwarden runtime startup diagnostics:"
  docker compose -f "$SCRIPT_DIR/docker-compose.yml" ps || true
  docker logs bitwarden_tls_proxy --tail 200 || true
  docker logs vaultwarden --tail 200 || true
  docker logs vaultwarden-db --tail 200 || true
}

# 1. Orchestrate backend containers (Vaultwarden + Postgres)
echo "[INFO] Orchestrating backend containers..."
docker compose -f "$SCRIPT_DIR/docker-compose.yml" down -v --remove-orphans 2>/dev/null || true
docker compose -f "$SCRIPT_DIR/docker-compose.yml" up -d --build
if ! wait_healthy "bitwarden_tls_proxy" 180; then
  dump_runtime_diagnostics
  fatal "bitwarden_tls_proxy did not become healthy"
fi

wait_for_host_alive() {
  local elapsed=0
  echo "[INFO] Waiting for Bitwarden TLS proxy to serve https://localhost:8000/alive (timeout ${HOST_ALIVE_TIMEOUT}s)..."

  while [ "$elapsed" -lt "$HOST_ALIVE_TIMEOUT" ]; do
    if curl --silent --show-error --fail --connect-timeout 5 --max-time 15 \
      --cacert "$ROOT_DIR/tls/rootCA.pem" \
      https://localhost:8000/alive >/dev/null; then
      echo "[INFO] Bitwarden TLS proxy is healthy."
      return 0
    fi

    sleep 5
    elapsed=$((elapsed + 5))
  done

  dump_runtime_diagnostics
  fatal "Timed out waiting for Bitwarden TLS proxy to serve /alive after ${HOST_ALIVE_TIMEOUT}s"
}

# 2. Verify the proxy endpoint from the host using the shared CA
wait_for_host_alive

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
