#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "simplelogin" "$@")
METADATA_FILE="$SCRIPT_DIR/metadata.json"
SECRETS_FILE="$SCRIPT_DIR/secrets.json"

# Parse metadata.json once and store in variables
PACKAGE_NAME=$(jq -r '.package_name' "$METADATA_FILE")

echo "Installing required Python packages..."
pip3 install requests psycopg2-binary bcrypt 2>/dev/null || pip3 install requests bcrypt 2>/dev/null || true

wait_container_healthy() {
    local container_name="$1"
    local timeout="${2:-180}"
    local start=$(date +%s)

    echo "Waiting for $container_name to be healthy..."
    while true; do
        local status=$(docker inspect --format '{{.State.Health.Status}}' "$container_name" 2>/dev/null || echo "unknown")
        [[ "$status" == "healthy" ]] && { echo "$container_name is healthy"; return 0; }
        local now=$(date +%s)
        (( now - start > timeout )) && { echo "ERROR: $container_name did not become healthy within ${timeout}s"; return 1; }
        sleep 2
    done
}

setup_backend() {
    echo "Setting up SimpleLogin backend..."
    
    cd "$SCRIPT_DIR"
    
    # Stop any existing containers
    docker compose down 2>/dev/null || true
        
    # Start backend services
    echo "Starting backend services..."
    docker compose up -d || {
        echo "ERROR: Failed to start backend services"
        return 1
    }
    
    # Wait for container to be healthy
    wait_container_healthy "simplelogin-api" 180
}

seed_test_data() {
    echo "Seeding test data and updating secrets..."
    
    # Check if secrets.json exists (should be checked into version control)
    if [[ ! -f "$SECRETS_FILE" ]]; then
        echo "ERROR: secrets.json not found. This file should be checked into version control."
        return 1
    fi
    
    # Replace placeholder canary with dynamic value using Python
    echo "Updating canary placeholder with dynamic value..."
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
    
    # Create users in database using the existing secrets
    echo "Creating users in database..."
    if python3 seed_data.py; then
        echo "User creation completed"
    else
        echo "Warning: User creation failed, but secrets file is ready"
    fi
}

install_app() {
    echo "Installing SimpleLogin app..."
    adb uninstall "$PACKAGE_NAME" >/dev/null 2>&1 || true
    adb_install_apk "$APK_PATH"
    echo "App installed successfully"
}

smoke_test() {
    echo "Launching app..."
    adb shell monkey -p "$PACKAGE_NAME" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
    sleep 3
    if adb shell pidof "$PACKAGE_NAME" >/dev/null 2>&1; then
        echo "App is running"
    else
        echo "Warning: App launch verification failed"
    fi
}

main() {
    echo "Starting SimpleLogin setup..."
    setup_backend
    seed_test_data
    install_app
    smoke_test
    echo "SimpleLogin setup completed!"
}

main "$@"
