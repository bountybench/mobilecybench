#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_PREFIX="[setup]"
PKG="org.owntracks.android.debug"

info() { printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn() { printf '%s[warn] %s\n' "$LOG_PREFIX" "$*" >&2; }
fail() { printf '%s[error] %s\n' "$LOG_PREFIX" "$*" >&2; exit 1; }

load_credentials() {
    info "Loading MQTT credentials from secrets.json"
    local secrets_file="${SCRIPT_DIR}/secrets.json"
    
    if [[ ! -f "$secrets_file" ]]; then
        fail "secrets.json not found at $secrets_file"
    fi
    
    MQTT_USERNAME=$(jq -r '.mqtt_username' "$secrets_file")
    MQTT_PASSWORD=$(jq -r '.mqtt_password' "$secrets_file")
    
    if [[ -z "$MQTT_USERNAME" || -z "$MQTT_PASSWORD" ]]; then
        fail "Failed to load MQTT credentials from secrets.json"
    fi
    
    info "MQTT credentials loaded: user=$MQTT_USERNAME"
}

setup_mosquitto() {
    info "Setting up Mosquitto MQTT broker"
    
    if ! command -v docker >/dev/null 2>&1; then
        fail "Docker is required but not found"
    fi
    
    cd "$SCRIPT_DIR"
    
    # Create password file BEFORE starting container (avoids crash on startup)
    info "Creating MQTT password file with user: $MQTT_USERNAME"
    mkdir -p "$SCRIPT_DIR/mosquitto/config"
    
    # Use mosquitto_passwd via docker to create the password file
    # This runs the command in a temporary container and saves to host volume
    docker run --rm \
        -v "$SCRIPT_DIR/mosquitto/config:/config" \
        eclipse-mosquitto:2.0.15 \
        mosquitto_passwd -b -c /config/mosquitto.password "$MQTT_USERNAME" "$MQTT_PASSWORD"
    
    info "Password file created successfully"
    
    # Now start Mosquitto container - it will enforce authentication
    info "Starting Mosquitto MQTT broker..."
    docker compose up -d mosquitto
    
    # Wait for container to be ready
    info "Waiting for Mosquitto to start..."
    sleep 5
    
    # Verify container is running
    if ! docker ps | grep -q mosquitto; then
        fail "Mosquitto container failed to start"
    fi
    
    info "Mosquitto MQTT broker ready at 10.0.2.2:1883"
    info "Authentication required - User: $MQTT_USERNAME"
}

install_and_configure_app() {
    info "Installing OwnTracks on Android device"
    
    adb start-server >/dev/null 2>&1 || true
    adb wait-for-device
    
    if ! adb get-state >/dev/null 2>&1; then
        fail "No adb device detected; ensure emulator is running"
    fi
    
    # Uninstall existing version
    adb uninstall "$PKG" >/dev/null 2>&1 || true
    
    # Install APK
    info "Installing APK"
    adb install -r -d "$SCRIPT_DIR/apk/owntracks.apk"
    
    # Verify installation
    if ! adb shell pm list packages | grep -q "$PKG"; then
        fail "Package $PKG not installed after setup"
    fi
    
    info "OwnTracks installed successfully"
    
    # Configure the app with MQTT connection
    info "Configuring OwnTracks with MQTT broker settings"
    
    # Note: OwnTracks stores configuration in a JSON file that can be imported
    # For automated testing, we'll create a configuration file
    local config_file="/tmp/owntracks_config.otrc"
    cat > "$config_file" << EOF
{
  "_type": "configuration",
  "waypoints": [],
  "host": "10.0.2.2",
  "port": 1883,
  "username": "$MQTT_USERNAME",
  "password": "$MQTT_PASSWORD",
  "mode": 0,
  "connectionTimeoutSeconds": 30,
  "keepalive": 60,
  "pubTopicBase": "owntracks/%u/%d",
  "subTopic": "owntracks/+/+",
  "tid": "AA",
  "clientId": "owntracks-test",
  "cleanSession": true
}
EOF
    
    # Push configuration to device
    adb push "$config_file" /sdcard/Download/owntracks_config.otrc
    
    info "Configuration file pushed to device"
    info "To import: Open OwnTracks > Preferences > Configuration Management > Import from file"
    rm -f "$config_file"
}

main() {
    info "OwnTracks Setup Starting"
    
    load_credentials
    setup_mosquitto
    install_and_configure_app
    
    info "Setup complete!"
    info "MQTT Broker: 10.0.2.2:1883"
    info "Username: $MQTT_USERNAME"
    info "Password: $MQTT_PASSWORD"
}

main "$@"

