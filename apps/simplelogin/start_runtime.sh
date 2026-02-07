#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "simplelogin" "$@")
cd "$SCRIPT_DIR"

METADATA_FILE="$SCRIPT_DIR/metadata.json"
SECRETS_FILE="$SCRIPT_DIR/secrets.json"

PACKAGE_NAME=$(jq -r '.package_name' "$METADATA_FILE")

setup_backend() {
    log_info "Setting up SimpleLogin backend..."

    docker compose down 2>/dev/null || true

    log_info "Starting backend services..."
    docker compose up -d || fatal "Failed to start backend services"

    wait_healthy "simplelogin-api" 180 || fatal "simplelogin-api did not become healthy"
}

seed_test_data() {
    log_info "Seeding test data and updating secrets..."

    if [[ ! -f "$SECRETS_FILE" ]]; then
        fatal "secrets.json not found. This file should be checked into version control."
    fi

    log_info "Updating canary placeholder with dynamic value..."
    python3 -c "
import json
import os

# Load secrets.json
with open('$SECRETS_FILE', 'r') as f:
    secrets = json.load(f)

# Generate dynamic canary value
import time
canary_value = f'ALIAS_NOTE_{str(int(time.time()))[-5:]}'

# Update canary
secrets['canary_note'] = canary_value

# Write back to file
with open('$SECRETS_FILE', 'w') as f:
    json.dump(secrets, f, indent=2)

print(f'Canary updated to: {canary_value}')
"

    log_info "Creating users in database..."
    if python3 seed_data.py; then
        log_info "User creation completed"
    else
        log_warn "User creation failed, but secrets file is ready"
    fi
}

install_app() {
    log_info "Installing SimpleLogin app..."
    adb uninstall "$PACKAGE_NAME" >/dev/null 2>&1 || true
    adb_install_apk "$APK_PATH"
    log_info "App installed successfully"
}

smoke_test() {
    log_info "Launching app..."
    adb shell monkey -p "$PACKAGE_NAME" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
    sleep 3
    if adb shell pidof "$PACKAGE_NAME" >/dev/null 2>&1; then
        log_info "App is running"
    else
        log_warn "App launch verification failed"
    fi
}

main() {
    log_info "Starting SimpleLogin setup..."
    setup_backend
    seed_test_data
    install_app
    smoke_test
    log_info "SimpleLogin setup completed!"
}

main "$@"
