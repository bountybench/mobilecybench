#!/usr/bin/env bash
# Grocy setup script - installs APK and starts Grocy server
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_PREFIX="[setup]"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
APK_DIR="$SCRIPT_DIR/apk"
METADATA_FILE="$SCRIPT_DIR/metadata.json"

# Read package name from metadata.json, fallback to release package
if [ -f "$METADATA_FILE" ]; then
  TARGET_PACKAGE=$(python3 -c "import json; print(json.load(open('$METADATA_FILE'))['package_name'])" 2>/dev/null || echo "xyz.zedler.patrick.grocy")
else
  TARGET_PACKAGE="xyz.zedler.patrick.grocy"
fi

info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*" >&2; }
error(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*"; exit 1; }

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

# --- Remove existing containers and volumes ---
cleanup_existing() {
  info "Cleaning up existing containers and volumes..."

  # Only run docker compose down if the file exists
  if [ -f "$COMPOSE_FILE" ]; then
    docker compose -f "$COMPOSE_FILE" down -v --remove-orphans 2>/dev/null || true
  fi

  docker ps -a --format "{{.Names}}" | grep -E "grocy-app" | xargs -r docker rm -f 2>/dev/null || true
  for vol in grocy_grocy_data grocy_data; do
    docker volume rm -f "$vol" 2>/dev/null || true
  done
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
  info "Starting Grocy Server..."

  cd "$SCRIPT_DIR"

  # Start services
  docker compose -f "$COMPOSE_FILE" up -d

  info "Services started, waiting for health checks..."
}

# --- Wait for services ---
wait_for_services() {
  info "Waiting for Grocy server..."

  # Wait for container to be healthy (docker-compose health check handles this)
  sleep 10

  # Single check - fail fast if not ready
  if ! curl -fsS http://127.0.0.1:9283 >/dev/null 2>&1; then
    error "Grocy server not responding. Check logs: docker compose -f $COMPOSE_FILE logs"
  fi

  info "Grocy server ready"
}

# --- Check for existing APK ---
check_existing_apk() {
  [ -f "$APK_DIR/grocy.apk" ] || error "No APK found at $APK_DIR/grocy.apk. Run setup_app_source.sh first."
}

# --- Install APK on emulator ---
install_android_app() {
  info "Installing APK..."
  adb uninstall "$TARGET_PACKAGE" 2>/dev/null || true
  adb install "$APK_DIR/grocy.apk" || error "Failed to install APK"
}

# --- Launch the app ---
launch_android_app() {
  info "Launching app..."
  adb shell monkey -p "$TARGET_PACKAGE" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
  sleep 2
}

# --- Print final status ---
print_status() {
  info "Setup complete"
  printf 'GROCY_SERVER_URL=http://10.0.2.2:9283\n'
  printf 'CONTAINERS=grocy-app\n'
  printf 'ANDROID_PACKAGE=%s\n' "$TARGET_PACKAGE"
}

# --- Main ---
main() {
  check_prerequisites
  cleanup_existing
  verify_compose_file
  start_services
  wait_for_services
  check_existing_apk
  install_android_app
  launch_android_app
  print_status
}

main "$@"


