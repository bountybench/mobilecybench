#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="SimpleX Chat"
APP_PACKAGE="chat.simplex.app"
APK_DIR="${SCRIPT_DIR}/apk"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yml"
SMP_CONTAINER="simplex-smp"
XFTP_CONTAINER="simplex-xftp"
APK_PATH=""
DEVICE_ID=""

log()  { printf '[setup] %s\n' "$*"; }
warn() { printf '[setup][warn] %s\n' "$*" >&2; }
fail() { printf '[setup][error] %s\n' "$*" >&2; exit 1; }

require_cmd() {
  local cmd="$1"
  command -v "$cmd" >/dev/null 2>&1 || fail "Required command '$cmd' not found"
}

compose() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    docker compose -f "$COMPOSE_FILE" "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose -f "$COMPOSE_FILE" "$@"
  else
    fail "Docker Compose is required to manage ${APP_NAME} support services"
  fi
}

ensure_networks() {
  if ! docker network inspect shared_net >/dev/null 2>&1; then
    log "Creating shared_net bridge network"
    docker network create shared_net >/dev/null
  fi
}

ensure_apk() {
  mkdir -p "$APK_DIR"
  local apk=""
  apk=$(find "$APK_DIR" -maxdepth 1 -name '*.apk' -print -quit 2>/dev/null || true)

  if [[ -z "$apk" ]]; then
    log "No APK found. Building ${APP_NAME} from source..."
    bash "$SCRIPT_DIR/setup_app_source.sh"
    apk=$(find "$APK_DIR" -maxdepth 1 -name '*.apk' -print -quit 2>/dev/null || true)
  fi

  [[ -n "$apk" ]] || fail "Unable to locate a built APK under $APK_DIR"
  APK_PATH="$apk"
  log "Using APK: $(basename "$APK_PATH")"
}

ensure_device() {
  require_cmd adb
  adb start-server >/dev/null 2>&1 || true

  log "Waiting for an emulator/device"
  if ! adb wait-for-device >/dev/null 2>&1; then
    fail "No Android device detected"
  fi

  DEVICE_ID=$(adb devices | awk 'NR>1 && $2=="device" {print $1; exit}')
  [[ -n "$DEVICE_ID" ]] || fail "Could not determine connected device ID"
  log "Using device $DEVICE_ID"
}

start_backends() {
  require_cmd docker
  ensure_networks
  log "Starting supporting containers"
  compose up -d
  wait_for_container "$SMP_CONTAINER"
  wait_for_container "$XFTP_CONTAINER"
}

wait_for_container() {
  local name="$1"
  for _ in {1..30}; do
    local state
    state=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$name" 2>/dev/null || echo "starting")
    if [[ "$state" == "healthy" || "$state" == "running" ]]; then
      log "Container $name is $state"
      return
    fi
    sleep 2
  done
  echo "Logs for container one"
  echo "---------------------------------------------"
  echo $(docker logs $(docker ps | awk 'NR==2 {print $1}'))
  echo "---------------------------------------------"
  echo $(docker logs $(docker ps | awk 'NR==3 {print $1}'))
  echo "---------------------------------------------"
  fail "Container $name did not become ready"
}

install_apk() {
  log "Installing ${APP_NAME} on $DEVICE_ID"
  adb -s "$DEVICE_ID" uninstall "$APP_PACKAGE" >/dev/null 2>&1 || true
  adb -s "$DEVICE_ID" install -r "$APK_PATH"
}

launch_app() {
  log "Launching ${APP_NAME}"
  adb -s "$DEVICE_ID" shell monkey -p "$APP_PACKAGE" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
  log "${APP_NAME} is ready"
}

main() {
  log "Starting ${APP_NAME} setup"
  ensure_apk
  start_backends
  ensure_device
  install_apk
  launch_app
  log "Setup complete"
}

main "$@"
