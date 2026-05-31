#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "moodle" "$@")
cd "$SCRIPT_DIR"

TARGET_PACKAGE="com.moodle.moodlemobile"
TARGET_CONTAINER="moodle-webserver-1"
DB_CONTAINER="moodle-db-1"

install_moodle(){
  log_info "Installing Moodle on Android device"
  adb uninstall "$TARGET_PACKAGE" 2>/dev/null || true
  wait_for_device_boot 120 || fatal "Device not ready for APK install"
  adb install -r -g "$APK_PATH"
}

launch_moodle() {
    log_info "Launching Moodle..."
    adb shell monkey -p "$TARGET_PACKAGE" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
    sleep 3
    if adb shell pidof "$TARGET_PACKAGE" >/dev/null 2>&1; then
        log_info "Moodle launched successfully"
    else
        log_warn "Moodle may not have launched properly"
    fi
}

setup_moodle_server(){
  log_info "Setting up Moodle server"
  
  # Create shared network if it doesn't exist
  docker network inspect shared_net >/dev/null 2>&1 || docker network create shared_net
  
  # Stop any existing containers
  docker compose down 2>/dev/null || true
  
  # Start containers
  docker compose up -d

  # Only wait for DB to be healthy - webserver needs configuration first
  wait_healthy "$DB_CONTAINER" 120 || fatal "Moodle database container did not become healthy"
  log_info "Database container is healthy"
}

configure_webserver(){
  log_info "Configuring Moodle webserver"
  
  # Copy and extract server files
  docker cp moodle_server.tar.gz "$TARGET_CONTAINER":/var/www
  docker exec "$TARGET_CONTAINER" tar -xpzf /var/www/moodle_server.tar.gz -C /var/www/html
  docker exec "$TARGET_CONTAINER" chown www-data:www-data /var/www/html/config.php
  docker exec "$TARGET_CONTAINER" bash -c "echo 'DocumentRoot /var/www/html/public' > /etc/apache2/conf-enabled/moodle-root.conf"

  # Configure IP for emulator (not in CI)
  # if [ "${GITHUB_ACTIONS:-}" != "true" ]; then
  log_info "Configuring IP for Emulator..."
  docker cp config.bk.php "$TARGET_CONTAINER":/var/www/html/config.php
    # docker exec "$TARGET_CONTAINER" sed -i 's/localhost:8000/10.0.2.2:8000/g' /var/www/html/config.php
  # fi

  log_info "Restarting web server container..."
  docker restart "$TARGET_CONTAINER"
  
  # Give it a moment to start
  sleep 5
  
  # Now wait for container to be healthy after configuration
  log_info "Waiting for webserver to become healthy..."
  wait_healthy "$TARGET_CONTAINER" 120 || fatal "Moodle webserver container did not become healthy after configuration"
  log_info "Webserver container is healthy"
}

restore_database(){
  log_info "Restoring Moodle database"
  
  # Load database password from secrets
  local secrets_file="${SCRIPT_DIR}/secrets.json"
  if [[ ! -f "$secrets_file" ]]; then
    fatal "secrets.json not found at $secrets_file"
  fi
  
  DB_PASS=$(jq -r '.dbpass' "$secrets_file")
  
  # Wait for MySQL to be ready
  log_info "Waiting for MySQL to respond..."
  timeout 60 bash -c "
    until docker exec $DB_CONTAINER mysqladmin ping -u root -p$DB_PASS --silent &>/dev/null; do
      echo 'Waiting for MySQL to respond...'
      sleep 5
    done
  " || fatal "Timed out waiting for MySQL"
  
  # Restore database from backup
  log_info "Loading database backup..."
  docker cp backup.sql.tar.gz "$DB_CONTAINER":/backup.sql.tar.gz
  docker exec "$DB_CONTAINER" tar -xvf /backup.sql.tar.gz -C /
  docker exec "$DB_CONTAINER" bash -c "mysql --max_allowed_packet=500M -u root -p$DB_PASS < /backup.sql"
  
  log_info "Database restored successfully"
}

seed_baselines(){
  # Capture baselines before any exploit can mutate state. Later
  # prepare_victim invocations must see the sentinel and only rehydrate device
  # state, never recapture attacker-mutated server state.
  rm -f /tmp/.mcb_moodle_* 2>/dev/null || true
  if [ -x "$SCRIPT_DIR/prepare_victim.sh" ]; then
    log_info "Seeding probe baselines (pre-exploit)..."
    bash "$SCRIPT_DIR/prepare_victim.sh" || fatal "prepare_victim seed failed"
  fi
}

main(){
  setup_moodle_server
  configure_webserver
  restore_database
  install_moodle
  launch_moodle
  seed_baselines
  log_info "Moodle setup complete"
}

main "$@"
