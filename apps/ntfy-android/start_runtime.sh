#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "ntfy-android" "$@")
cd "$SCRIPT_DIR"

HEALTH_TIMEOUT=${HEALTH_TIMEOUT:-180}

TARGET_PACKAGE="io.heckel.ntfy"
TARGET_DIR="/data/data/${TARGET_PACKAGE}"
ANDROID_BASELINE_FILE="${SCRIPT_DIR}/baseline_android_dir.txt"
EMULATOR_GATEWAY="http://10.0.2.2:8080"

start_stack() {
  log_info "Starting ntfy-server"
  docker compose up -d --remove-orphans
}

wait_for_health() {
  wait_healthy ntfy-server "$HEALTH_TIMEOUT" || fatal "ntfy-server did not become healthy"
}

install_app() {
  log_info "Installing ntfy-android"
  adb uninstall "$TARGET_PACKAGE" >/dev/null 2>&1 || true
  adb_install_apk "$APK_PATH"
}

configure_app_defaults() {
  log_info "Pointing app to local Docker server..."

  adb shell "am force-stop $TARGET_PACKAGE" >/dev/null 2>&1

  local pref_file_name="MainPreferences.xml"
  cat <<EOF > "$pref_file_name"
<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <string name="DefaultBaseURL">$EMULATOR_GATEWAY</string>
    <string name="ConnectionProtocol">jsonhttp</string>
</map>
EOF

  if ! adb push "$pref_file_name" /data/local/tmp/ >/dev/null 2>&1; then
    rm "$pref_file_name"
    fatal "Failed to push preferences file"
  fi

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
    fatal "Failed to configure app preferences"
  fi

  rm "$pref_file_name"

  adb shell sync >/dev/null 2>&1
  log_info "App preferences updated. DefaultBaseURL set to $EMULATOR_GATEWAY"
}

launch_app() {
  log_info "Launching ntfy..."
  adb shell am start -n "$TARGET_PACKAGE/.ui.MainActivity" >/dev/null 2>&1 || log_warn "Failed to launch app"
  sleep 2
}

capture_baseline() {
  log_info "Capturing Android baseline -> $ANDROID_BASELINE_FILE"
  adb shell su 0 find "$TARGET_DIR" 2>/dev/null | tr -d '\r' | sort > "$ANDROID_BASELINE_FILE" || log_warn "Baseline capture failed"
}

run_ntfy_seeding() {
  log_info "Running ntfy seeding"
  cd "$SCRIPT_DIR"
  if command -v uv >/dev/null 2>&1; then
    uv run python ntfy_seeding.py || log_warn "ntfy_seeding.py failed"
  else
    python3 ntfy_seeding.py || log_warn "ntfy_seeding.py failed"
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
  log_info "Setup complete for ntfy"
}

main "$@"
