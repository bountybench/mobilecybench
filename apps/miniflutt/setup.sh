#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APK_PATH="${ROOT_DIR}/apk/miniflutt.apk"

log() { echo "[setup] $*"; }

start_services() {
  log "Starting Miniflux backend services..."

  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    docker compose -f "${ROOT_DIR}/docker-compose.yml" up -d
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
  if [[ ! -f "${APK_PATH}" ]]; then
    log "ERROR: APK not found at ${APK_PATH}"
    exit 1
  fi

  log "Connected devices:"
  adb devices || true

  log "Installing Miniflutt APK..."
  adb install -r "${APK_PATH}" || {
    log "WARNING: adb install failed; maybe app already installed? Trying with -d -t..."
    adb install -r -d -t "${APK_PATH}"
  }

  log "APK installation step complete."
}

main() {
  log "Running miniflutt setup..."

  # check emulator running
  if ! adb devices | grep -q "device\|emulator"; then
    echo "ERROR: No Android emulator found."
    echo "Please start the emulator first."
    exit 1
  fi

  start_services
  wait_for_miniflux
  install_apk

  log "Setup complete."
}

main "$@"
