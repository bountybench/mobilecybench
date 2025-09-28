#!/usr/bin/env bash
# Gotify Server + PostgreSQL setup with Docker Compose
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_PREFIX="[setup]"
ENV_FILE="$SCRIPT_DIR/.env"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
CODEBASE_DIR="$SCRIPT_DIR/codebase"
TARGET_PACKAGE="com.github.gotify"

info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*" >&2; }
error(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*"; exit 1; }

# Clean up any stale artifacts from previous runs
pre_setup_cleanup() {
  rm -f /tmp/unauth_response.txt 2>/dev/null || true
  pkill -f "curl.*localhost:8080" 2>/dev/null || true
}

# --- Check prerequisites ---
check_prerequisites() {
  command -v docker >/dev/null 2>&1 || error "Docker not found on PATH"
  command -v curl >/dev/null 2>&1 || error "curl not found on PATH"
  command -v adb >/dev/null 2>&1 || error "adb not found on PATH"

  # Check if Docker daemon is running
  docker info >/dev/null 2>&1 || error "Docker daemon is not running"

  # Check if emulator is running
  if ! adb devices | grep -q "device\|emulator"; then
    error "No Android emulator found. Please start the emulator first."
  fi
}

# --- Generate strong passwords ---
generate_password() {
  openssl rand -base64 32 | tr -d "=+/" | cut -c1-25
}

# --- Remove existing containers and volumes (no data persistence) ---
cleanup_existing() {
  info "Cleaning up existing containers and volumes..."

  # Only run docker compose down if the file exists
  if [ -f "$COMPOSE_FILE" ]; then
    docker compose -f "$COMPOSE_FILE" down -v --remove-orphans 2>/dev/null || true
  fi

  docker ps -a --format "{{.Names}}" | grep -E "gotify-(server|db)" | xargs -r docker rm -f 2>/dev/null || true
  for vol in gotify_gotify_data gotify_pg_data postgres_data gotify_data pg_data; do
    docker volume rm -f "$vol" 2>/dev/null || true
  done
}

# --- Create/update .env file ---
create_env_file() {
  info "Creating/updating .env file..."

  # Generate passwords if .env doesn't exist or if passwords are empty
  if [ ! -f "$ENV_FILE" ]; then
    GOTIFY_ADMIN_PASS="$(generate_password)"
    DB_PASSWORD="$(generate_password)"
  else
    # Source existing .env and generate missing passwords (with validation)
    if [ -r "$ENV_FILE" ] && grep -q '=' "$ENV_FILE" 2>/dev/null; then
      # shellcheck source=/dev/null
      source "$ENV_FILE" 2>/dev/null || true
    fi
    GOTIFY_ADMIN_PASS="${GOTIFY_ADMIN_PASS:-$(generate_password)}"
    DB_PASSWORD="${DB_PASSWORD:-$(generate_password)}"
  fi

  cat > "$ENV_FILE" << EOF
GOTIFY_BASE_URL=http://10.0.2.2:8080

GOTIFY_ADMIN_USER=admin
GOTIFY_ADMIN_PASS=$GOTIFY_ADMIN_PASS

DB_ENGINE=postgres
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=gotify
DB_USER=gotify
DB_PASSWORD=$DB_PASSWORD
EOF

  info ".env file created/updated"
}

# --- Verify Docker Compose file exists ---
verify_compose_file() {
  if [ ! -f "$COMPOSE_FILE" ]; then
    error "Docker Compose file not found: $COMPOSE_FILE"
  fi
  info "Using Docker Compose file: $COMPOSE_FILE"
}

# --- Start services ---
start_services() {
  info "Starting Gotify Server and PostgreSQL..."

  cd "$SCRIPT_DIR"

  # Start services
  docker compose -f "$COMPOSE_FILE" up -d

  info "Services started, waiting for health checks..."
}

# --- Wait for services ---
wait_for_services() {
  info "Polling Gotify server health..."

  max_attempts=24  # 120 seconds with 5-second intervals
  attempt=0

  while [ $attempt -lt $max_attempts ]; do
    attempt=$((attempt + 1))

    # Try health endpoint first, then fallback to root
    if curl -fsS http://127.0.0.1:8080/health >/dev/null 2>&1 || curl -fsS http://127.0.0.1:8080/ >/dev/null 2>&1; then
      info "Gotify server is ready!"
      return 0
    fi

    if [ $attempt -eq $max_attempts ]; then
      error "Gotify server failed to start after 120 seconds. Check logs."
    fi

    info "Attempt $attempt/$max_attempts - waiting for Gotify server..."
    sleep 5
  done
}

# --- Print final status ---
# --- Check for existing APK ---
check_existing_apk() {
  info "Checking for existing APK..."

  # Check if APK exists in apk directory (built by setup_app_source.sh)
  if [ -f "$SCRIPT_DIR/apk/gotify.apk" ]; then
    info "Found APK: $SCRIPT_DIR/apk/gotify.apk"
    return 0
  fi

  error "No APK found at $SCRIPT_DIR/apk/gotify.apk. Please run setup_app_source.sh first to build the APK."
}

# --- Install APK on emulator ---
install_android_app() {
  info "Installing Gotify APK on Android emulator..."

  APK_PATH="$SCRIPT_DIR/apk/gotify.apk"

  if [ ! -f "$APK_PATH" ]; then
    error "APK not found at $APK_PATH"
  fi

  info "Installing APK: $APK_PATH"

  # Uninstall existing app first to avoid conflicts
  adb uninstall "$TARGET_PACKAGE" 2>/dev/null || true

  # Install the APK
  if adb install "$APK_PATH"; then
    info "APK installed successfully"
  else
    error "Failed to install APK"
  fi
}

# --- Launch the app ---
launch_android_app() {
  info "Launching Gotify app..."

  # Get the correct main activity name from the APK
  MAIN_ACTIVITY=$(adb shell dumpsys package "$TARGET_PACKAGE" | grep -A 1 "android.intent.action.MAIN:" | grep "$TARGET_PACKAGE" | awk '{print $2}' | head -1)

  if [ -n "$MAIN_ACTIVITY" ]; then
    info "Launching main activity: $MAIN_ACTIVITY"
    adb shell am start -n "$MAIN_ACTIVITY" >/dev/null 2>&1
  else
    # Fallback to common activity names
    info "Trying common activity names..."
    adb shell am start -n "$TARGET_PACKAGE/.MainActivity" >/dev/null 2>&1 || \
    adb shell am start -n "$TARGET_PACKAGE/.activity.MainActivity" >/dev/null 2>&1 || \
    adb shell monkey -p "$TARGET_PACKAGE" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
  fi

  sleep 3

  # Verify the app is installed and can be found
  if adb shell pm list packages | grep -q "$TARGET_PACKAGE"; then
    info "Gotify app is installed and ready!"
  else
    warn "App installation may have failed"
  fi
}

print_status() {
  info "Setup completed successfully!"

  # Source .env for absolute path
  # shellcheck source=/dev/null
  source "$ENV_FILE"

  printf 'APP_SERVER_URL=http://10.0.2.2:8080\n'
  printf 'ENV_PATH=%s\n' "$ENV_FILE"
  printf 'CONTAINERS=gotify,db\n'
  printf 'ANDROID_PACKAGE=%s\n' "$TARGET_PACKAGE"
}

# --- Error diagnostics ---
show_diagnostics() {
  warn "Setup failed. Showing diagnostics..."

  if [ -f "$COMPOSE_FILE" ]; then
    warn "Last 200 lines of database logs:"
    docker compose -f "$COMPOSE_FILE" logs --tail=200 db || true

    warn "Last 200 lines of Gotify logs:"
    docker compose -f "$COMPOSE_FILE" logs --tail=200 gotify || true

    warn "Testing connectivity:"
    curl -v http://127.0.0.1:8080/ || true
  fi
}

# --- Main ---
main() {
  info "Setting up Gotify: Server with PostgreSQL + Android APK installation..."

  # Set trap for error diagnostics
  trap show_diagnostics ERR

  pre_setup_cleanup
  check_prerequisites
  cleanup_existing
  create_env_file
  verify_compose_file
  start_services
  wait_for_services
  check_existing_apk
  install_android_app
  launch_android_app
  print_status

  exit 0
}

main "$@"