#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="Syncthing-Fork"
APP_PACKAGE="com.github.catfriend1.syncthingfork"
APK_DIR="${SCRIPT_DIR}/apk"
APK_PATH=""
DEVICE_ID=""

log()  { printf '[setup] %s\n' "$*"; }
warn() { printf '[setup][warn] %s\n' "$*" >&2; }
fail() { printf '[setup][error] %s\n' "$*" >&2; exit 1; }

require_cmd() {
  local cmd="$1"
  command -v "$cmd" >/dev/null 2>&1 || fail "Required command '$cmd' not found"
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
  ensure_device
  install_apk
  launch_app
  log "Setup complete"
}

main "$@"
