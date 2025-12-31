#!/usr/bin/env bash
# Environment + baseline setup script for ntfy CIAA tests.
# Steps:
#   1. Verify prerequisites (docker, python3, uv, adb)
#   2. Launch docker-compose stack (ntfy-server)
#   3. Wait for server health
#   4. Install Android app from: ./apk/ntfy-android.apk (must exist before running)
#   5. Configure app defaults (Set default server to 10.0.2.2:8080)
#   6. Capture Android directory baseline for integrity checks
# Usage:
#   ./setup.sh

set -euo pipefail
IFS=$'\n\t'

# --- Configuration ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}" )" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yml"
VENV_DIR="${SCRIPT_DIR}/.venv"
HEALTH_TIMEOUT=${HEALTH_TIMEOUT:-180}
HEALTH_INTERVAL=5
LOG_PREFIX="[setup-ntfy]"

TARGET_PACKAGE="io.heckel.ntfy"
TARGET_DIR="/data/data/${TARGET_PACKAGE}"
ANDROID_BASELINE_FILE="${SCRIPT_DIR}/baseline_android_dir.txt"
NTFY_URL="http://localhost:8080" # Host perspective
EMULATOR_GATEWAY="http://10.0.2.2:8080" # Emulator perspective

info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*" >&2; }
fail(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*" >&2; exit 1; }
command_exists(){ command -v "$1" >/dev/null 2>&1; }

ensure_prereqs() {
  info "Checking prerequisites"
  command_exists docker || fail "docker is required"
  command_exists adb || fail "adb is required"
  if ! command_exists uv; then
    info "Installing uv..."
    curl -Ls https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
  fi
}

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose -f "$COMPOSE_FILE" "$@"
  elif command_exists docker-compose; then
    docker-compose -f "$COMPOSE_FILE" "$@"
  else
    fail "docker compose plugin or docker-compose binary not available"
  fi
}

start_stack() {
  info "Starting ntfy-server"
  compose up -d --remove-orphans >/dev/null 2>&1
}

wait_for_health() {
  info "Waiting for ntfy-server health (timeout ${HEALTH_TIMEOUT}s)"
  local start; start=$(date +%s)
  while true; do
    local status; status=$(docker inspect --format '{{.State.Health.Status}}' ntfy-server 2>/dev/null || echo "unknown")
    if [[ "$status" == "healthy" ]]; then
      info "ntfy-server healthy"
      break
    fi
    local now; now=$(date +%s)
    if (( now - start > HEALTH_TIMEOUT )); then
      docker ps --format 'table {{.Names}}\t{{.Status}}'
      fail "Timed out waiting for ntfy-server (last status: $status)"
    fi
    sleep "$HEALTH_INTERVAL"
  done
}

install_app() {
  info "Installing ntfy-android from local APK folder"
  adb wait-for-device >/dev/null 2>&1
  if ! adb get-state >/dev/null 2>&1; then
    fail "No adb device detected; ensure an emulator/device is running"
  fi

  local apk="${SCRIPT_DIR}/apk/ntfy-android.apk"
  [[ -f "$apk" ]] || fail "APK not found at $apk"
  
  adb uninstall "$TARGET_PACKAGE" >/dev/null 2>&1 || true
  if ! adb install -r "$apk" >/dev/null 2>&1; then
    fail "Failed to install APK"
  fi
  info "APK installed successfully"
}

configure_app_defaults() {
  info "Pointing app to local Docker server..."
  
  # 1. Kill app and clear the specific cached prefs from the system
  adb shell "am force-stop $TARGET_PACKAGE" >/dev/null 2>&1
  
  # 2. Inject the DefaultBaseURL key (as defined in Repository.SHARED_PREFS_DEFAULT_BASE_URL)
  local pref_file_name="MainPreferences.xml"
  cat <<EOF > "$pref_file_name"
<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <string name="DefaultBaseURL">$EMULATOR_GATEWAY</string>
    <string name="ConnectionProtocol">jsonhttp</string>
</map>
EOF

  # 3. Push to temporary location
  if ! adb push "$pref_file_name" /data/local/tmp/ >/dev/null 2>&1; then
    rm "$pref_file_name"
    fail "Failed to push preferences file"
  fi
  
  # 4. Atomic move and permission fix
  if ! adb shell su 0 <<EOF >/dev/null 2>&1
    mkdir -p /data/data/$TARGET_PACKAGE/shared_prefs
    mv /data/local/tmp/$pref_file_name /data/data/$TARGET_PACKAGE/shared_prefs/
    
    # Standard Android permissions
    chmod 660 /data/data/$TARGET_PACKAGE/shared_prefs/$pref_file_name
    APP_UID=\$(stat -c %u /data/data/$TARGET_PACKAGE)
    chown \$APP_UID:\$APP_UID /data/data/$TARGET_PACKAGE/shared_prefs/$pref_file_name
    
    # Force the OS to acknowledge the file change (suppress verbose output)
    restorecon /data/data/$TARGET_PACKAGE/shared_prefs/$pref_file_name 2>/dev/null || true
EOF
  then
    rm "$pref_file_name"
    fail "Failed to configure app preferences"
  fi

  rm "$pref_file_name"
  
  # 5. Wait before launching to let the OS sync the file system
  sleep 1
  info "App preferences updated. DefaultBaseURL set to $EMULATOR_GATEWAY"
}

launch_app() {
  info "Launching ntfy..."
  adb shell am start -n "$TARGET_PACKAGE/.ui.MainActivity" >/dev/null 2>&1
  sleep 2
}

capture_baseline() {
  info "Capturing Android baseline -> $ANDROID_BASELINE_FILE"
  # Requirement for Integrity Probes: List all files in the app's internal storage
  adb shell su 0 find "$TARGET_DIR" 2>/dev/null | tr -d '\r' | sort > "$ANDROID_BASELINE_FILE" || warn "Baseline capture failed"
}


main() {
  ensure_prereqs
  start_stack
  wait_for_health
  install_app
  configure_app_defaults
  launch_app
  capture_baseline
  info "Setup complete for ntfy"
}

main "$@"