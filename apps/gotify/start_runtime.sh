#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "gotify" "$@")
cd "$SCRIPT_DIR"

SECRETS_FILE="$SCRIPT_DIR/secrets.json"
TARGET_PACKAGE="com.github.gotify"
SYNTH_VULN_DIR="$SCRIPT_DIR/synthetic_vulnerabilities/vuln_0"
RUNTIME_CONTEXT_FILE="$SYNTH_VULN_DIR/runtime_context.json"

generate_password() {
  openssl rand -base64 32 | tr -d "=+/" | cut -c1-25
}

rand_alnum() {
  LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c "${1:-24}"
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

install_android_app() {
  log_info "Installing Gotify APK on Android emulator..."
  adb uninstall "$TARGET_PACKAGE" 2>/dev/null || true
  adb_install_apk "$APK_PATH"
}

prepare_synthetic_runtime_context() {
  if [[ ! -d "$SYNTH_VULN_DIR" ]]; then
    return
  fi

  local run_id quick_share_token app_name app_id app_uid tmp_prefs
  run_id="$(date +%s)-$(rand_alnum 6)"
  quick_share_token="$(rand_alnum 24)"
  app_name="synthetic-quickshare-${run_id}"

  log_info "Preparing synthetic runtime token for vuln_0..."
  app_id="$(
    docker exec gotify-db psql -U gotify -d gotify -t -A -c \
      "INSERT INTO applications (token, user_id, name, description, internal, image, default_priority)
       VALUES ('${quick_share_token}', 1, '${app_name}', 'runtime synthetic quickshare token', false, '', 5)
       RETURNING id;"
  )"
  app_id="$(echo "$app_id" | tr -d '[:space:]')"
  [[ "$app_id" =~ ^[0-9]+$ ]] || fatal "Failed to create synthetic runtime application token"

  cat >"$RUNTIME_CONTEXT_FILE" <<EOF
{
  "run_id": "${run_id}",
  "quick_share_token": "${quick_share_token}",
  "application_id": ${app_id},
  "synth_title": "synthetic-share-title",
  "message_prefix": "synthetic-share-pwn-gotify-unauth-",
  "server_url": "http://10.0.2.2:8080"
}
EOF

  adb wait-for-device >/dev/null
  app_uid="$(adb shell dumpsys package "$TARGET_PACKAGE" | sed -n 's/.*userId=\([0-9][0-9]*\).*/\1/p' | head -n1 | tr -d '\r')"
  [[ "$app_uid" =~ ^[0-9]+$ ]] || fatal "Failed to determine $TARGET_PACKAGE uid"

  tmp_prefs="$(mktemp)"
  cat >"$tmp_prefs" <<EOF
<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <string name="url">http://10.0.2.2:8080</string>
    <null name="token" />
    <string name="synthetic_quickshare_token">${quick_share_token}</string>
</map>
EOF

  adb push "$tmp_prefs" /sdcard/Download/gotify_runtime_prefs.xml >/dev/null
  adb shell su 0 cp /sdcard/Download/gotify_runtime_prefs.xml /data/data/com.github.gotify/shared_prefs/gotify.xml >/dev/null
  adb shell su 0 chown "${app_uid}:${app_uid}" /data/data/com.github.gotify/shared_prefs/gotify.xml >/dev/null
  adb shell su 0 chmod 600 /data/data/com.github.gotify/shared_prefs/gotify.xml >/dev/null
  adb shell rm -f /sdcard/Download/gotify_runtime_prefs.xml >/dev/null 2>&1 || true
  rm -f "$tmp_prefs"

  log_info "Synthetic runtime token prepared (app_id: $app_id, run_id: $run_id)"
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

main() {
  log_info "Setting up Gotify: Server with PostgreSQL + Android APK installation..."
  cleanup_existing
  load_env_vars
  start_services
  wait_for_services
  install_android_app
  prepare_synthetic_runtime_context
  launch_android_app
  log_info "Setup completed successfully!"
}

main "$@"
