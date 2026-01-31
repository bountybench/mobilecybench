#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "grocy" "$@")
cd "$SCRIPT_DIR"

source .env
GROCY_URL="http://localhost:8080"

log_info "Creating necessary directories..."
mkdir -p files/config

log_info "Running Docker compose..."
docker compose up -d

wait_healthy grocy-server 60 || log_warn "Server health check timed out, continuing anyway..."

log_info "Triggering Grocy database initialization..."
curl -f -s "${GROCY_URL}" > /dev/null || true
sleep 5

log_info "Injecting API key into Grocy database..."
docker cp inject_api_key.php grocy-server:/tmp/inject_api_key.php
docker exec grocy-server php /tmp/inject_api_key.php "${GROCY_API_KEY}"

log_info "Injecting testuser into Grocy database..."
docker cp inject_testuser.php grocy-server:/tmp/inject_testuser.php
docker exec grocy-server php /tmp/inject_testuser.php

log_info "Installing Grocy Android on emulator..."
adb_install_apk "$APK_PATH"
log_info "Grocy Android installed successfully."

log_info "Launching Grocy Android..."
adb shell monkey -p xyz.zedler.patrick.grocy -c android.intent.category.LAUNCHER 1

log_info "Configuring Grocy Android through UI automation..."
pip3 install -q uiautomator2 2>/dev/null || pip3 install --break-system-packages -q uiautomator2

python3 "$SCRIPT_DIR/setup_grocy_ui.py" \
    --server-url "http://10.0.2.2:8080" \
    --api-key "demo_api_key_for_testing"

log_info "Setup complete! Grocy is ready for testing."
