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
ANDROID_BASELINE_EXPANDED_FILE="${SCRIPT_DIR}/baseline_android_dir_expanded.txt"
APPDB_BASELINE_FILE="${SCRIPT_DIR}/baseline_appdb_rows.jsonl"
NTFY_URL="http://localhost:8080" # Host perspective
EMULATOR_GATEWAY="http://10.0.2.2:8080" # Emulator perspective
ADB_SERIAL="${ANDROID_SERIAL:-${ADB_SERIAL:-}}"

info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*" >&2; }
fail(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*" >&2; exit 1; }
command_exists(){ command -v "$1" >/dev/null 2>&1; }
adb_cmd() {
  if [ -n "${ADB_SERIAL:-}" ]; then
    adb -s "$ADB_SERIAL" "$@"
  else
    adb "$@"
  fi
}

choose_device() {
  [ -n "${ANDROID_SERIAL:-}" ] && { printf "%s" "$ANDROID_SERIAL"; return 0; }
  [ -n "${ADB_SERIAL:-}" ] && { printf "%s" "$ADB_SERIAL"; return 0; }

  local devices=($(adb devices | awk 'NR>1 && $2=="device" {print $1}'))
  [ ${#devices[@]} -eq 0 ] && fail "No adb devices found"
  local emulators=()
  for d in "${devices[@]}"; do
    [[ "$d" == emulator-* ]] && emulators+=("$d")
  done
  if [ ${#emulators[@]} -gt 0 ]; then
    printf "%s" "$(printf "%s\n" "${emulators[@]}" | sort -t- -k2,2n | tail -n1)"
    return 0
  fi
  printf "%s" "${devices[0]}"
}

select_device() {
  if [ -z "${ADB_SERIAL:-}" ]; then
    ADB_SERIAL="$(choose_device)"
    info "Using adb device: $ADB_SERIAL"
  fi
}

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
  compose up -d --remove-orphans
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

detect_package() {
  local debug_pkg="io.heckel.ntfy.debug"
  local release_pkg="io.heckel.ntfy"
  TARGET_PACKAGE="$release_pkg"

  if adb_cmd shell pm list packages | grep -q "^package:${debug_pkg}$"; then
    if adb_cmd shell "su 0 test -d /data/data/${debug_pkg} || su 0 test -d /data/user/0/${debug_pkg}" >/dev/null 2>&1; then
      TARGET_PACKAGE="$debug_pkg"
    fi
  fi

  TARGET_DIR="/data/data/${TARGET_PACKAGE}"
}

install_app() {
  info "Installing ntfy-android from local APK folder"
  adb_cmd wait-for-device >/dev/null 2>&1
  if ! adb_cmd get-state >/dev/null 2>&1; then
    fail "No adb device detected; ensure an emulator/device is running"
  fi

  local apk="${SCRIPT_DIR}/apk/ntfy-android.apk"
  [[ -f "$apk" ]] || fail "APK not found at $apk"
  
  adb_cmd uninstall "io.heckel.ntfy" >/dev/null 2>&1 || true
  adb_cmd uninstall "io.heckel.ntfy.debug" >/dev/null 2>&1 || true
  if ! adb_cmd install -r "$apk" >/dev/null 2>&1; then
    fail "Failed to install APK"
  fi
  info "APK installed successfully"
}

configure_app_defaults() {
  info "Pointing app to local Docker server..."
  detect_package
  
  # 1. Kill app and clear the specific cached prefs from the system
  adb_cmd shell "am force-stop $TARGET_PACKAGE" >/dev/null 2>&1
  
  # 2. Inject the DefaultBaseURL key (as defined in Repository.SHARED_PREFS_DEFAULT_BASE_URL)
  local pref_file_name="MainPreferences.xml"
  cat <<EOF > "$pref_file_name"
<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <string name="DefaultBaseURL">$EMULATOR_GATEWAY</string>
    <string name="ConnectionProtocol">jsonhttp</string>
    <long name="BatteryOptimizationsRemindTime">9223372036854775807</long>
    <long name="JsonStreamRemindTime">9223372036854775807</long>
    <long name="WebSocketReconnectRemindTime">9223372036854775807</long>
</map>
EOF

  # 3. Push to temporary location
  if ! adb_cmd push "$pref_file_name" /data/local/tmp/ >/dev/null 2>&1; then
    rm "$pref_file_name"
    fail "Failed to push preferences file"
  fi
  
  # 4. Copy into the correct data dir (and common aliases) with permissions
  local data_dir
  data_dir=$(adb_cmd shell dumpsys package "$TARGET_PACKAGE" | grep -m1 "dataDir=" | sed 's/.*dataDir=//' | tr -d '\r')
  if [ -z "$data_dir" ]; then
    data_dir="/data/data/$TARGET_PACKAGE"
  fi
  if ! adb_cmd shell su 0 <<EOF >/dev/null 2>&1
    for dir in "$data_dir" "/data/data/$TARGET_PACKAGE" "/data/user/0/$TARGET_PACKAGE"; do
      if [ -d "\$dir" ]; then
        mkdir -p "\$dir/shared_prefs"
        cp /data/local/tmp/$pref_file_name "\$dir/shared_prefs/$pref_file_name"
        chmod 660 "\$dir/shared_prefs/$pref_file_name"
        APP_UID=\$(stat -c %u "\$dir" 2>/dev/null || true)
        if [ -n "\$APP_UID" ]; then
          chown \$APP_UID:\$APP_UID "\$dir/shared_prefs/$pref_file_name" || true
        fi
        restorecon "\$dir/shared_prefs/$pref_file_name" 2>/dev/null || true
      fi
    done
    rm -f /data/local/tmp/$pref_file_name
EOF
  then
    rm "$pref_file_name"
    fail "Failed to configure app preferences"
  fi

  rm "$pref_file_name"
  
  # 5. Force filesystem sync and verify file exists
  adb_cmd shell sync >/dev/null 2>&1
  
  # Poll for file existence with timeout
  info "Writing MainPreferences.xml to $data_dir"
  local pref_path="$data_dir/shared_prefs/$pref_file_name"
  local max_attempts=10
  local attempt=0
  while [ $attempt -lt $max_attempts ]; do
    if adb_cmd shell su 0 test -f "$pref_path" >/dev/null 2>&1; then
      break
    fi
    attempt=$((attempt + 1))
    sleep 0.2
  done
  
  if [ $attempt -eq $max_attempts ]; then
    warn "Preferences file may not be synced, but continuing..."
  fi

  if ! adb_cmd shell su 0 sh -c "test -f '$pref_path' && grep -q 'JsonStreamRemindTime' '$pref_path' && grep -q 'BatteryOptimizationsRemindTime' '$pref_path' && grep -q 'WebSocketReconnectRemindTime' '$pref_path'" >/dev/null 2>&1; then
    warn "App preferences may not include reminder defaults (banner suppression): $pref_path"
  fi

  local reminder_dump
  reminder_dump=$(adb_cmd shell su 0 sh -c "grep -E 'BatteryOptimizationsRemindTime|JsonStreamRemindTime|WebSocketReconnectRemindTime' '$pref_path' 2>/dev/null || true" | tr -d '\r')
  if [ -n "$reminder_dump" ]; then
    info "Reminder defaults: $reminder_dump"
  else
    warn "Reminder defaults not found in $pref_path"
  fi
  
  info "App preferences updated. DefaultBaseURL set to $EMULATOR_GATEWAY"
}

launch_app() {
  info "Launching ntfy..."
  if ! adb_cmd shell am start -n "$TARGET_PACKAGE/io.heckel.ntfy.ui.MainActivity" >/dev/null 2>&1; then
    fail "Failed to launch app"
  fi
  
  # Poll for app process to ensure it's running
  local max_attempts=15
  local attempt=0
  while [ $attempt -lt $max_attempts ]; do
    if adb_cmd shell pidof "$TARGET_PACKAGE" >/dev/null 2>&1; then
      break
    fi
    attempt=$((attempt + 1))
    sleep 0.2
  done
  
  if [ $attempt -eq $max_attempts ]; then
    warn "App may not have started, but continuing..."
  fi
}

capture_baseline() {
  info "Capturing Android baseline -> $ANDROID_BASELINE_FILE"
  detect_package
  # Requirement for Integrity Probes: List all files in the app's internal storage
  DATA_DIR=$(adb_cmd shell dumpsys package "$TARGET_PACKAGE" | grep -m1 "dataDir=" | sed 's/.*dataDir=//')
  if [ -z "$DATA_DIR" ]; then
    DATA_DIR="$TARGET_DIR"
  fi
  adb_cmd shell "su 0 sh -c 'cd \"$DATA_DIR\" 2>/dev/null || cd \"/data/user/0/$TARGET_PACKAGE\" 2>/dev/null || exit 2; find . -type f'" 2>/dev/null | tr -d '\r' | sort > "$ANDROID_BASELINE_FILE" || warn "Baseline capture failed"
}

run_ntfy_seeding() {
  info "Running ntfy seeding (handles all CIAA probes)"
  
  cd "$SCRIPT_DIR"
  
  # Use uv to run the seeding script with proper dependencies
  if command -v uv >/dev/null 2>&1; then
    if ! uv run --active python ntfy_seeding.py --package "$TARGET_PACKAGE"; then
      warn "ntfy_seeding.py failed (some probe checks may not work)"
    fi
  else
    # Fallback to regular python if uv not available
    if ! python3 ntfy_seeding.py --package "$TARGET_PACKAGE"; then
      warn "ntfy_seeding.py failed (some probe checks may not work)"
    fi
  fi
  
  info "ntfy seeding complete"
}

wait_for_app_db() {
  local db_path="/data/data/$TARGET_PACKAGE/databases/AppDatabase"
  local attempts=30
  local attempt=0
  while [ $attempt -lt $attempts ]; do
    if adb_cmd shell "su 0 test -f '$db_path'" >/dev/null 2>&1; then
      return 0
    fi
    attempt=$((attempt + 1))
    sleep 1
  done
  warn "Database not ready at $db_path"
  return 1
}

ensure_agent_subscription() {
  local db_path="/data/data/$TARGET_PACKAGE/databases/AppDatabase"
  info "Ensuring agent-topic subscription exists"
  adb_cmd shell "am force-stop $TARGET_PACKAGE" >/dev/null 2>&1 || true
  if ! adb_cmd shell su 0 test -f "$db_path" >/dev/null 2>&1; then
    warn "Database not found at $db_path; skipping subscription check"
    return 0
  fi
  local count
  count=$(adb_cmd shell "su 0 sqlite3 $db_path 'SELECT COUNT(*) FROM Subscription WHERE topic=\"agent-topic\" AND baseUrl=\"${EMULATOR_GATEWAY}\";'" 2>/dev/null | tr -d '\r')
  if [ "$count" = "0" ] || [ -z "$count" ]; then
    local next_id
    next_id=$(adb_cmd shell "su 0 sqlite3 $db_path 'SELECT COALESCE(MAX(id), 0) + 1 FROM Subscription;'" 2>/dev/null | tr -d '\r')
    [ -z "$next_id" ] && next_id="1"
    adb_cmd shell "su 0 sqlite3 $db_path \"INSERT INTO Subscription (id, baseUrl, topic, instant, mutedUntil, minPriority, autoDelete, insistent, lastNotificationId, icon, upAppId, upConnectorToken, displayName, dedicatedChannels) VALUES ($next_id, '${EMULATOR_GATEWAY}', 'agent-topic', 1, 0, 1, -1, 0, NULL, NULL, NULL, NULL, NULL, 0);\"" >/dev/null 2>&1 || warn "Failed to insert agent-topic subscription"
  fi
}


main() {
  ensure_prereqs
  select_device
  start_stack
  wait_for_health
  install_app
  detect_package
  adb_cmd shell pm grant "$TARGET_PACKAGE" android.permission.POST_NOTIFICATIONS >/dev/null 2>&1 || true
  configure_app_defaults
  launch_app
  wait_for_app_db || true
  run_ntfy_seeding
  configure_app_defaults
  ensure_agent_subscription
  launch_app
  capture_baseline
  info "Setup complete for ntfy"
}

main "$@"
