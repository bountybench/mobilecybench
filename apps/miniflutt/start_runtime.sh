#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "miniflutt" "$@")

log() { echo "[setup] $*"; }

start_services() {
  log "Starting Miniflux backend services..."

  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    docker compose -f "${SCRIPT_DIR}/docker-compose.yml" up -d
  else 
    log "docker compose not found"
    exit 1
  fi
}

wait_for_miniflux() {
  log "Waiting for Miniflux to become healthy..."
  local max_tries=30
  local try=0

  until curl -fsS "http://localhost:8080/healthcheck" >/dev/null 2>&1; do
    try=$((try + 1))
    if [[ "$try" -ge "$max_tries" ]]; then
      log "ERROR: Miniflux did not become healthy in time"
      exit 1
    fi
    sleep 2
  done

  log "Miniflux is healthy."
}

install_apk() {
  log "Installing Miniflutt APK..."
  adb_install_apk "$APK_PATH"
  log "APK installation step complete."
}

main() {
  log "Running miniflutt setup..."
  start_services
  wait_for_miniflux
  install_apk

  log "Setup complete."
}

main "$@"
