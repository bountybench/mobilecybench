#!/usr/bin/env bash
# Gotify Server + PostgreSQL setup with Docker Compose
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "gotify" "$@")
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
SECRETS_FILE="$SCRIPT_DIR/secrets.json"
TARGET_PACKAGE="com.github.gotify"
LOG_PREFIX="[setup]"

info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*" >&2; }
error(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*"; exit 1; }

generate_password() {
  openssl rand -base64 32 | tr -d "=+/" | cut -c1-25
}

cleanup_existing() {
  info "Cleaning up existing containers and volumes..."
  docker compose -f "$COMPOSE_FILE" down -v --remove-orphans 2>/dev/null || true
}

load_env_vars() {
  info "Loading environment variables from secrets.json..."
  [[ -f "$SECRETS_FILE" ]] || error "secrets.json not found at $SECRETS_FILE"

  export GOTIFY_ADMIN_USER="admin"
  export GOTIFY_ADMIN_PASS=$(jq -r '.ADMIN_PASSWORD' "$SECRETS_FILE")
  export DB_NAME="gotify"
  export DB_USER="gotify"
  export DB_PASSWORD="$(generate_password)"
}

start_services() {
  info "Starting Gotify Server and PostgreSQL..."
  cd "$SCRIPT_DIR"
  docker compose -f "$COMPOSE_FILE" build seeder
  docker compose -f "$COMPOSE_FILE" up -d
  info "Services started, waiting for health checks..."
}

wait_for_services() {
  info "Polling Gotify server health..."
  for attempt in $(seq 1 24); do
    if curl -fsS http://127.0.0.1:8080/health >/dev/null 2>&1; then
      info "Gotify server is ready!"
      break
    fi
    [[ $attempt -eq 24 ]] && error "Gotify server failed to start after 120 seconds."
    sleep 5
  done

  info "Waiting for database seeding to complete..."
  for attempt in $(seq 1 12); do
    seeder_status=$(docker inspect gotify-seeder --format='{{.State.Status}}' 2>/dev/null || echo "not_found")
    if [[ "$seeder_status" == "exited" ]]; then
      seeder_exit_code=$(docker inspect gotify-seeder --format='{{.State.ExitCode}}' 2>/dev/null || echo "1")
      [[ "$seeder_exit_code" == "0" ]] && { info "Database seeding completed!"; break; }
      error "Database seeding failed (exit code $seeder_exit_code)"
    fi
    [[ $attempt -eq 12 ]] && error "Database seeding timeout"
    sleep 5
  done
}

install_android_app() {
  info "Installing Gotify APK on Android emulator..."
  adb uninstall "$TARGET_PACKAGE" 2>/dev/null || true
  adb_install_apk "$APK_PATH"
}

launch_android_app() {
  info "Launching Gotify app..."
  adb shell monkey -p "$TARGET_PACKAGE" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
  sleep 3
  if adb shell pm list packages | grep -q "$TARGET_PACKAGE"; then
    info "Gotify app is installed and ready!"
  else
    warn "App installation may have failed"
  fi
}

main() {
  info "Setting up Gotify: Server with PostgreSQL + Android APK installation..."
  cleanup_existing
  load_env_vars
  start_services
  wait_for_services
  install_android_app
  launch_android_app
  info "Setup completed successfully!"
}

main "$@"
