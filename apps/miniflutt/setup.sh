#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APK_PATH="${ROOT_DIR}/apk/miniflutt.apk"

log() { echo "[setup] $*"; }

start_services() {
  log "Starting Miniflux backend services..."

  if command -v docker-compose >/dev/null 2>&1; then
    docker-compose -f "${ROOT_DIR}/docker-compose.yml" up -d
  elif command -v docker >/dev/null 2>&1; then
    docker compose -f "${ROOT_DIR}/docker-compose.yml" up -d
  else
    log "ERROR: docker / docker-compose not found"
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

ensure_emulator() {
  log "Ensuring Android emulator/device is running..."

  if ! command -v adb >/dev/null 2>&1; then
    log "ERROR: adb not found. Run the repo-level setup.sh to install Android SDK / tools."
    exit 1
  fi

  # Any connected device/emulator already?
  local count
  count=$(adb devices | awk 'NR>1 && $2=="device"{n++} END{print n+0}')
  if [[ "$count" -gt 0 ]]; then
    log "Found $count connected Android device(s). Waiting for device to be ready..."
    adb wait-for-device
    return 0
  fi

  # No devices – try to start emulator via repo-level script
  local REPO_ROOT="${ROOT_DIR}/../.."
  local START_EMU="${REPO_ROOT}/start_emulator.sh"
  local REPO_SETUP="${REPO_ROOT}/setup.sh"

  if [[ -x "$START_EMU" ]]; then
    log "No emulator detected. Starting one via ${START_EMU}..."
    "${START_EMU}" &
    log "Waiting for emulator to come online via adb wait-for-device..."
    adb wait-for-device
    return 0
  fi

  log "ERROR: ${START_EMU} not found or not executable. Run the repo-level setup.sh first."
  exit 1
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

  start_services
  wait_for_miniflux
  ensure_emulator
  install_apk

  log "Setup complete."
}

main "$@"
