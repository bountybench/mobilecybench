#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "linphone" "$@")
cd "$SCRIPT_DIR"

pip install uiautomator2 psycopg2-binary mysql-connector-python bcrypt pytest dotenv 2>/dev/null || true

install_linphone() {
    log_info "Installing linphone on Android emulator..."
    adb_install_apk "$APK_PATH"
    log_info "linphone installed successfully."
}

launch_linphone() {
    log_info "Launching linphone..."
    adb_launch_activity "org.linphone/.ui.main.MainActivity"
    log_info "linphone should now be running on your emulator."
}

setup_linphone_server() {
  log_info "Setting up Flexisip (Linphone SIP server)"
  docker compose up -d --build account_db flexisip

  log_info "Waiting for Flexisip container health check..."
  for i in {1..15}; do
    health_status=$(docker inspect --format='{{.State.Health.Status}}' flexisip 2>/dev/null || echo "no-health")
    [[ "$health_status" = "healthy" ]] && { log_info "Flexisip container is healthy"; break; }
    [[ $i -eq 15 ]] && log_warn "Flexisip health check still not healthy, proceeding anyway..."
    sleep 2
  done

  docker exec -i account_db mysql -u flexisip -pzoSt4w4wreu flexisip_accounts < seed.sql
  log_info "Flexisip server ready"
}

synch_with_server() {
    log_info "Synching app with server..."
    python synch_app.py --username usera --password userAPW123
}

main() {
    log_info "linphone Android Setup"
    setup_linphone_server
    install_linphone
    launch_linphone
    synch_with_server

    for i in {1..3}; do
        adb wait-for-device
        if adb root; then
            break
        fi
        log_info "Retrying adb root..."
        sleep 5
    done

    local immutable_dirs=(/system /vendor /product /odm)
    adb_hash_dirs "${immutable_dirs[@]}" > baseline.json

    local secret_dirs=(/data/cache /data/misc)
    adb_hide_secret_files "secrets.json" "${secret_dirs[@]}"

    adb unroot
    log_info "Setup complete!"
}

main "$@"
