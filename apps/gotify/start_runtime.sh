#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "gotify" "$@")
cd "$SCRIPT_DIR"

SECRETS_FILE="$SCRIPT_DIR/secrets.json"
TARGET_PACKAGE="com.github.gotify"

generate_password() {
  openssl rand -base64 32 | tr -d "=+/" | cut -c1-25
}

cleanup_existing() {
  log_info "Cleaning up existing containers and volumes..."
  docker compose down -v --remove-orphans 2>/dev/null || true
}

load_env_vars() {
  log_info "Loading environment variables from secrets.json..."
  [[ -f "$SECRETS_FILE" ]] || fatal "secrets.json not found at $SECRETS_FILE"

  export GOTIFY_ADMIN_USER="admin"
  export GOTIFY_ADMIN_PASS=$(jq -r '.ADMIN_PASSWORD' "$SECRETS_FILE")
  export DB_NAME="gotify"
  export DB_USER="gotify"
  export DB_PASSWORD="$(generate_password)"
}

start_services() {
  log_info "Starting Gotify Server and PostgreSQL..."
  docker compose build seeder
  docker compose up -d
  log_info "Services started, waiting for health checks..."
}

wait_for_services() {
  log_info "Polling Gotify server health..."
  for attempt in $(seq 1 24); do
    if curl -fsS http://127.0.0.1:8080/health >/dev/null 2>&1; then
      log_info "Gotify server is ready!"
      break
    fi
    [[ $attempt -eq 24 ]] && fatal "Gotify server failed to start after 120 seconds."
    sleep 5
  done

  log_info "Waiting for database seeding to complete..."
  for attempt in $(seq 1 12); do
    seeder_status=$(docker inspect gotify-seeder --format='{{.State.Status}}' 2>/dev/null || echo "not_found")
    if [[ "$seeder_status" == "exited" ]]; then
      seeder_exit_code=$(docker inspect gotify-seeder --format='{{.State.ExitCode}}' 2>/dev/null || echo "1")
      [[ "$seeder_exit_code" == "0" ]] && { log_info "Database seeding completed!"; break; }
      fatal "Database seeding failed (exit code $seeder_exit_code)"
    fi
    [[ $attempt -eq 12 ]] && fatal "Database seeding timeout"
    sleep 5
  done
}

create_agent_user() {
  log_info "Ensuring non-admin agent user exists..."
  local response code
  response=$(curl -s -u "${GOTIFY_ADMIN_USER}:${GOTIFY_ADMIN_PASS}" \
    -H "Content-Type: application/json" \
    -d '{"name":"agent","pass":"agentpass","admin":false}' \
    -w "\n%{http_code}" \
    http://127.0.0.1:8080/user || true)
  code=$(echo "$response" | tail -n 1)
  case "$code" in
    200|201) log_info "Agent user created." ;;
    400|409) log_info "Agent user already exists." ;;
    *)       log_warn "Failed to create agent user (HTTP $code)." ;;
  esac
}

install_android_app() {
  log_info "Installing Gotify APK on Android emulator..."
  adb uninstall "$TARGET_PACKAGE" 2>/dev/null || true
  adb_install_apk "$APK_PATH"
}

launch_android_app() {
  log_info "Launching Gotify app..."
  adb shell monkey -p "$TARGET_PACKAGE" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
  sleep 3
  if adb shell pm list packages | grep -q "$TARGET_PACKAGE"; then
    log_info "Gotify app is installed and ready!"
  else
    log_warn "App installation may have failed"
  fi
}

login_agent_user() {
  log_info "Logging in as agent user..."
  if python3 "$SCRIPT_DIR/ui_automation/login.py" \
      --server-url "http://localhost:8080" \
      --username "agent" \
      --password "agentpass"; then
    log_info "Agent user logged in successfully"
  else
    fatal "Failed to login agent user"
  fi
}

main() {
  log_info "Setting up Gotify: Server with PostgreSQL + Android APK installation..."
  cleanup_existing
  load_env_vars
  start_services
  wait_for_services
  create_agent_user
  install_android_app
  launch_android_app
  login_agent_user
  log_info "Setup completed successfully!"
}

main "$@"
