#!/usr/bin/env bash
# Gotify Server + PostgreSQL setup with Docker Compose
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_PREFIX="[setup]"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
APP_SOURCE_SCRIPT="$SCRIPT_DIR/setup_app_source.sh"
SECRETS_FILE="$SCRIPT_DIR/secrets.json"

CODEBASE_DIR="$SCRIPT_DIR/codebase"
TARGET_PACKAGE="com.github.gotify"

info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*" >&2; }
error(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*"; exit 1; }

# Clean up any stale artifacts from previous runs
pre_setup_cleanup() {
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

# --- Load environment variables ---
load_env_vars() {
  info "Loading environment variables from secrets.json..."

  if [ ! -f "$SECRETS_FILE" ]; then
    error "secrets.json not found at $SECRETS_FILE"
  fi

  # Export variables for docker-compose
  export GOTIFY_ADMIN_USER="admin"
  export GOTIFY_ADMIN_PASS=$(jq -r '.ADMIN_PASSWORD' "$SECRETS_FILE")
  export DB_NAME="gotify"
  export DB_USER="gotify"
  export DB_PASSWORD="$(generate_password)"

  info "Environment variables loaded from secrets.json"
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

  # Build the seeder image first
  info "Building seeder image..."
  docker compose -f "$COMPOSE_FILE" build seeder

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

    # Try health endpoint first, then fallback to version endpoint
    if curl -fsS http://127.0.0.1:8080/health >/dev/null 2>&1 || curl -fsS http://127.0.0.1:8080/version >/dev/null 2>&1; then
      info "Gotify server is ready!"
      break
    fi

    if [ $attempt -eq $max_attempts ]; then
      error "Gotify server failed to start after 120 seconds. Check logs."
    fi

    info "Attempt $attempt/$max_attempts - waiting for Gotify server..."
    sleep 5
  done

  # Wait for seeder to complete
  info "Waiting for database seeding to complete..."
  max_seed_attempts=12  # 60 seconds with 5-second intervals
  seed_attempt=0

  while [ $seed_attempt -lt $max_seed_attempts ]; do
    seed_attempt=$((seed_attempt + 1))

    # Check if seeder container has exited with success
    seeder_status=$(docker inspect gotify-seeder --format='{{.State.Status}}' 2>/dev/null || echo "not_found")

    if [ "$seeder_status" = "exited" ]; then
      seeder_exit_code=$(docker inspect gotify-seeder --format='{{.State.ExitCode}}' 2>/dev/null || echo "1")
      if [ "$seeder_exit_code" = "0" ]; then
        info "Database seeding completed successfully!"
        return 0
      else
        warn "Seeder exited with code $seeder_exit_code. Checking logs..."
        docker logs gotify-seeder 2>&1 | tail -20
        error "Database seeding failed"
      fi
    fi

    if [ $seed_attempt -eq $max_seed_attempts ]; then
      warn "Seeder did not complete after 60 seconds. Current status: $seeder_status"
      docker logs gotify-seeder 2>&1 | tail -20
      error "Database seeding timeout"
    fi

    info "Attempt $seed_attempt/$max_seed_attempts - waiting for seeder..."
    sleep 5
  done
}

create_agent_user() {
  info "Ensuring non-admin agent user exists..."
  local payload
  local response
  local code

  payload='{"name":"agent","pass":"agentpass","admin":false}'
  response=$(curl -s -u "${GOTIFY_ADMIN_USER}:${GOTIFY_ADMIN_PASS}" \
    -H "Content-Type: application/json" \
    -d "$payload" \
    -w "\n%{http_code}" \
    http://127.0.0.1:8080/user || true)

  code=$(echo "$response" | tail -n 1)
  case "$code" in
    200|201)
      info "Agent user created."
      ;;
    400|409)
      info "Agent user already exists."
      ;;
    *)
      warn "Failed to create agent user (HTTP $code)."
      ;;
  esac
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

  # Ensure ADB server is running and device is connected
  if ! adb devices | grep -q "device\|emulator"; then
    error "No Android device/emulator found. Please ensure emulator is running."
  fi

  # Wait for device to be fully ready
  info "Waiting for device to be ready..."
  adb wait-for-device
  sleep 2

  # Uninstall existing app first to avoid conflicts (with retries)
  info "Uninstalling existing app (if present)..."
  max_uninstall_attempts=3
  uninstall_attempt=0
  while [ $uninstall_attempt -lt $max_uninstall_attempts ]; do
    if adb uninstall "$TARGET_PACKAGE" 2>/dev/null; then
      info "App uninstalled successfully"
      break
    else
      uninstall_attempt=$((uninstall_attempt + 1))
      if [ $uninstall_attempt -lt $max_uninstall_attempts ]; then
        warn "Uninstall attempt $uninstall_attempt failed, retrying..."
        sleep 2
        # Reset ADB connection
        adb kill-server 2>/dev/null || true
        sleep 1
        adb start-server 2>/dev/null || true
        adb wait-for-device
      fi
    fi
  done

  # Install the APK (with retries for transient errors)
  max_install_attempts=3
  install_attempt=0
  
  while [ $install_attempt -lt $max_install_attempts ]; do
    install_attempt=$((install_attempt + 1))
    
    if [ $install_attempt -gt 1 ]; then
      info "Install attempt $install_attempt/$max_install_attempts..."
      # Reset ADB connection between retries
      adb kill-server 2>/dev/null || true
      sleep 2
      adb start-server 2>/dev/null || true
      adb wait-for-device
      sleep 2
    fi

    # Try installation with streamed install for large APKs
    if adb install -r "$APK_PATH" 2>&1 | tee /tmp/adb_install.log; then
      info "APK installed successfully"
      rm -f /tmp/adb_install.log
      return 0
    else
      install_error=$(cat /tmp/adb_install.log 2>/dev/null || echo "unknown error")
      rm -f /tmp/adb_install.log
      
      # Check for specific recoverable errors
      if echo "$install_error" | grep -qiE "Broken pipe|DELETE_FAILED|device.*not found"; then
        if [ $install_attempt -lt $max_install_attempts ]; then
          warn "Transient error detected, retrying: $install_error"
          sleep 3
          continue
        fi
      fi
      
      # Non-recoverable error or max attempts reached
      if [ $install_attempt -eq $max_install_attempts ]; then
        error "Failed to install APK after $max_install_attempts attempts"
        error "Last error: $install_error"
        error "Try running: ./cleanup.sh && ./setup.sh"
      fi
    fi
  done
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

  printf 'APP_SERVER_URL=http://10.0.2.2:8080\n'
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
  check_existing_apk
  cleanup_existing
  load_env_vars
  verify_compose_file
  start_services
  wait_for_services
  install_android_app
  create_agent_user
  launch_android_app
  print_status

  exit 0
}

main "$@"
