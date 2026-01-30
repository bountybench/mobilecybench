#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}" )" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "ntfy-android" "$@")
HEALTH_TIMEOUT=${HEALTH_TIMEOUT:-180}
LOG_PREFIX="[setup-ntfy]"

TARGET_PACKAGE="io.heckel.ntfy"
TARGET_DIR="/data/data/${TARGET_PACKAGE}"
ANDROID_BASELINE_FILE="${SCRIPT_DIR}/baseline_android_dir.txt"
EMULATOR_GATEWAY="http://10.0.2.2:8080"

info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*" >&2; }
fail(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*" >&2; exit 1; }

start_stack() {
  info "Starting ntfy-server"
  docker compose -f "$SCRIPT_DIR/docker-compose.yml" up -d --remove-orphans
}

wait_for_health() {
  info "Waiting for ntfy-server health (timeout ${HEALTH_TIMEOUT}s)"
  local start; start=$(date +%s)
  while true; do
    local status; status=$(docker inspect --format '{{.State.Health.Status}}' ntfy-server 2>/dev/null || echo "unknown")
    [[ "$status" == "healthy" ]] && { info "ntfy-server healthy"; break; }
    local now; now=$(date +%s)
    (( now - start > HEALTH_TIMEOUT )) && fail "Timed out waiting for ntfy-server (last status: $status)"
    sleep 5
  done
}

install_app() {
  info "Installing ntfy-android"
  adb uninstall "$TARGET_PACKAGE" >/dev/null 2>&1 || true
  adb_install_apk "$APK_PATH"
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
  
  adb shell sync >/dev/null 2>&1
  info "App preferences updated. DefaultBaseURL set to $EMULATOR_GATEWAY"
}

launch_app() {
  info "Launching ntfy..."
  adb shell am start -n "$TARGET_PACKAGE/.ui.MainActivity" >/dev/null 2>&1 || warn "Failed to launch app"
  sleep 2
}

capture_baseline() {
  info "Capturing Android baseline -> $ANDROID_BASELINE_FILE"
  # Requirement for Integrity Probes: List all files in the app's internal storage
  adb shell su 0 find "$TARGET_DIR" 2>/dev/null | tr -d '\r' | sort > "$ANDROID_BASELINE_FILE" || warn "Baseline capture failed"
}

run_ntfy_seeding() {
  info "Running ntfy seeding"
  cd "$SCRIPT_DIR"
  if command -v uv >/dev/null 2>&1; then
    uv run python ntfy_seeding.py || warn "ntfy_seeding.py failed"
  else
    python3 ntfy_seeding.py || warn "ntfy_seeding.py failed"
  fi
}

main() {
  start_stack
  wait_for_health
  install_app
  configure_app_defaults
  launch_app
  run_ntfy_seeding
  capture_baseline
  info "Setup complete for ntfy"
}

main "$@"