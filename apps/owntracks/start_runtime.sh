#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "owntracks" "$@")
cd "$SCRIPT_DIR"

load_credentials() {
    local metadata_file="${SCRIPT_DIR}/metadata.json"
    if [[ ! -f "$metadata_file" ]]; then
        fatal "metadata.json not found at $metadata_file"
    fi

    PKG=$(jq -r '.package_name' "$metadata_file")
    AGENT_USERNAME=$(jq -r '.username' "$metadata_file")
    AGENT_PASSWORD=$(jq -r '.password' "$metadata_file")

    if [[ -z "$PKG" || -z "$AGENT_USERNAME" || -z "$AGENT_PASSWORD" ]]; then
        fatal "Failed to load package name or agent credentials from metadata.json"
    fi

    local secrets_file="${SCRIPT_DIR}/secrets.json"
    if [[ ! -f "$secrets_file" ]]; then
        fatal "secrets.json not found at $secrets_file"
    fi

    ADMIN_USERNAME=$(jq -r '.admin_username' "$secrets_file")
    ADMIN_PASSWORD=$(jq -r '.admin_password' "$secrets_file")

    if [[ -z "$ADMIN_USERNAME" || -z "$ADMIN_PASSWORD" ]]; then
        fatal "Failed to load admin credentials from secrets.json"
    fi

    log_info "Agent credentials loaded: user=$AGENT_USERNAME"
    log_info "Admin credentials loaded: user=$ADMIN_USERNAME"
}

setup_mosquitto() {
    log_info "Setting up Mosquitto MQTT broker"

    log_info "Creating MQTT password file with agent and admin users"
    mkdir -p "$SCRIPT_DIR/mosquitto/config"

    docker run --rm \
        -v "$SCRIPT_DIR/mosquitto/config:/config" \
        eclipse-mosquitto:2.0.15 \
        mosquitto_passwd -b -c /config/mosquitto.password "$AGENT_USERNAME" "$AGENT_PASSWORD"

    docker run --rm \
        -v "$SCRIPT_DIR/mosquitto/config:/config" \
        eclipse-mosquitto:2.0.15 \
        mosquitto_passwd -b /config/mosquitto.password "$ADMIN_USERNAME" "$ADMIN_PASSWORD"

    log_info "Password file created with agent user ($AGENT_USERNAME) and admin user ($ADMIN_USERNAME)"

    log_info "Starting Mosquitto MQTT broker..."
    # If the container already exists, it may have attempted to start previously (or be reused in a
    # dev workflow). In that case we restart after updating pwfile/ACL so it reloads state.
    local had_existing_container="false"
    if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "mosquitto"; then
        had_existing_container="true"
    fi
    docker compose up -d mosquitto
    if [[ "$had_existing_container" == "true" ]]; then
        log_info "Restarting Mosquitto to reload password/ACL files"
        docker compose restart mosquitto
    fi

    log_info "Waiting for Mosquitto to start..."
    for i in $(seq 1 15); do
        docker ps | grep -q mosquitto && break
        [[ $i -eq 15 ]] && fatal "Mosquitto container failed to start"
        sleep 2
    done

    log_info "Mosquitto MQTT broker ready at 10.0.2.2:1883"
    log_info "Authentication required - Agent user: $AGENT_USERNAME, Admin user: $ADMIN_USERNAME"
}

install_and_configure_app() {
    log_info "Installing OwnTracks on Android device"
    adb uninstall "$PKG" >/dev/null 2>&1 || true
    adb_install_apk "$APK_PATH"

    log_info "Granting runtime permissions"
    for perm in android.permission.ACCESS_FINE_LOCATION \
                android.permission.ACCESS_COARSE_LOCATION \
                android.permission.ACCESS_BACKGROUND_LOCATION \
                android.permission.POST_NOTIFICATIONS; do
        adb shell pm grant "$PKG" "$perm" 2>/dev/null || true
    done

    log_info "Launching OwnTracks and completing welcome wizard"
    adb shell am start -n "$PKG/.ui.map.MapActivity"
    sleep 3
    python3 "$SCRIPT_DIR/ui_automation/welcome_wizard.py"
    log_info "Welcome wizard completed"

    log_info "Configuring OwnTracks with MQTT broker settings"

    local config_file="/tmp/owntracks_config.otrc"
    cat > "$config_file" << EOF
{
  "_type": "configuration",
  "waypoints": [],
  "host": "10.0.2.2",
  "port": 1883,
  "username": "$AGENT_USERNAME",
  "password": "$AGENT_PASSWORD",
  "mode": 0,
  "connectionTimeoutSeconds": 30,
  "keepalive": 60,
  "pubTopicBase": "owntracks/%u/%d",
  "subTopic": "owntracks/+/+",
  "tid": "AA",
  "clientId": "owntracks-test",
  "tls": false,
  "cleanSession": true
}
EOF

    adb push "$config_file" /sdcard/Download/owntracks_config.otrc

    log_info "Configuration file pushed to device"
    log_info "To import: Open OwnTracks > Preferences > Configuration Management > Import from file"
    rm -f "$config_file"
}

main() {
    log_info "OwnTracks Setup Starting"

    load_credentials
    setup_mosquitto
    install_and_configure_app

    log_info "Setup complete!"
    log_info "MQTT Broker: 10.0.2.2:1883"
    log_info "Agent credentials (from metadata.json): $AGENT_USERNAME / $AGENT_PASSWORD"
    log_info "Admin credentials (from secrets.json): $ADMIN_USERNAME / $ADMIN_PASSWORD"
}

main "$@"
