#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "miniflutt" "$@")
cd "$SCRIPT_DIR"

start_services() {
  log_info "Starting Miniflux backend services..."
  docker compose up -d
}

wait_for_miniflux() {
  log_info "Waiting for Miniflux to become healthy..."
  local max_tries=30
  local try=0

  until curl -fsS "http://localhost:8080/healthcheck" >/dev/null 2>&1; do
    try=$((try + 1))
    if [[ "$try" -ge "$max_tries" ]]; then
      fatal "Miniflux did not become healthy in time"
    fi
    sleep 2
  done

  log_info "Miniflux is healthy."
}

install_apk() {
  log_info "Installing Miniflutt APK..."
  adb_install_apk "$APK_PATH"
  log_info "APK installation step complete."
}

main() {
  log_info "Running miniflutt setup..."
  start_services
  wait_for_miniflux
  install_apk

  log_info "Setup complete."
}

main "$@"
