#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
METADATA_FILE="$SCRIPT_DIR/metadata.json"
SECRETS_FILE="$SCRIPT_DIR/secrets.json"

# Parse metadata.json once and store in variables
PACKAGE_NAME=$(jq -r '.package_name' "$METADATA_FILE")
EMULATOR_SERVER=$(jq -r '.emulator_server' "$METADATA_FILE")
COMMIT_VERSION=$(jq -r '.commit_version' "$METADATA_FILE")

# Use modern Docker Compose v2
DC="docker compose"

echo "Installing required Python packages..."
pip3 install requests psycopg2-binary bcrypt 2>/dev/null || {
    echo "Warning: Some packages failed to install, trying individual installation..."
    pip3 install requests bcrypt 2>/dev/null || pip3 install requests
}

check_prerequisites() {
    echo "Checking prerequisites..."
    
    # Check Docker
    if ! command -v docker &> /dev/null; then
        echo "ERROR:" "Docker not found. Please install Docker."
        return 1
    fi
    
    # Check for docker compose
    if ! $DC version &> /dev/null; then
        echo "ERROR:" "docker compose not available. Please ensure Docker Compose is installed."
        return 1
    fi
    
    # Check jq
    if ! command -v jq &> /dev/null; then
        echo "ERROR:" "jq not found. Please install jq for JSON processing."
        return 1
    fi
    
    # Check curl
    if ! command -v curl &> /dev/null; then
        echo "ERROR:" "curl not found. Please install curl."
        return 1
    fi
    
    echo "Prerequisites check passed"
}

wait_container_healthy() {
    local cid="$1"
    local timeout="${2:-180}"
    local start ts status

    start="$(date +%s)"
    while :; do
        status="$(docker inspect -f '{{.State.Health.Status}}' "$cid" 2>/dev/null || echo 'no-health')"
        ts="$(date +%H:%M:%S)"
        echo "[$ts] ${cid:0:12} health: $status"

        if [[ "$status" == "healthy" ]]; then
            echo "INFO: API healthy"
            return 0
        fi

        # If the image has no healthcheck at all, fallback to "running + port open".
        if [[ "$status" == "no-health" ]]; then
            st="$(docker inspect -f '{{.State.Status}}' "$cid" 2>/dev/null || true)"
            if [[ "$st" == "running" ]]; then
                if docker compose exec -T simplelogin-api nc -z localhost 7777 2>/dev/null; then
                    echo "INFO: API reachable without healthcheck"
                    return 0
                fi
            fi
        fi

        # timeout guard
        if (( $(date +%s) - start > timeout )); then
            echo "ERROR: API did not become healthy within ${timeout}s"
            docker ps -a
            docker compose logs --no-color --tail=200 simplelogin-api db || true
            return 1
        fi

        sleep 3
    done
}

setup_backend() {
    echo "Setting up SimpleLogin backend..."
    
    cd "$SCRIPT_DIR"
    
    # Ensure Docker is running
    if ! docker info >/dev/null 2>&1; then
        echo "Starting Docker..."
        if [[ "$OSTYPE" == "darwin"* ]]; then
            # macOS
            open -a Docker
            echo "Waiting for Docker to start..."
            local timeout=60
            local counter=0
            while [[ $counter -lt $timeout ]]; do
                if docker info >/dev/null 2>&1; then
                    echo "Docker is running"
                    break
                fi
                sleep 2
                ((counter++))
            done
            
            if [[ $counter -eq $timeout ]]; then
                echo "ERROR: Docker failed to start within 60 seconds"
                return 1
            fi
        else
            echo "ERROR: Docker is not running. Please start Docker manually."
            return 1
        fi
    fi
    
    # Stop any existing containers
    $DC down 2>/dev/null || true
        
    # Start backend services
    echo "Starting backend services..."
    if ! $DC up -d; then
        echo "ERROR:" "Failed to start backend services"
        return 1
    fi
    
    # Wait for services to be healthy with robust health checking
    echo "Waiting for backend services to be ready..."
    
    # Get the container ID (stable across compose versions)
    local API_CID
    API_CID="$(docker compose ps -q simplelogin-api)"
    if [[ -z "$API_CID" ]]; then
        echo "ERROR: simplelogin-api container id not found"
        docker compose ps
        return 1
    fi
    
    # Robust health wait
    wait_container_healthy "$API_CID" 180
    
    # Wait for API port availability using Python socket check
    echo "Waiting for API port availability..."
    while ! docker compose exec -T simplelogin-api python -c 'import socket; s=socket.socket(); s.settimeout(5); s.connect(("localhost", 7777)); s.close()' 2>/dev/null; do
        echo "Waiting for SimpleLogin API server to be ready..."
        docker compose logs simplelogin-api
        echo "==================="
        sleep 2
    done
    echo "SimpleLogin API server is ready!"
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

build_and_install_app() {
    echo "Building and installing SimpleLogin app..."
    
    # Check if app is already installed and up-to-date
    local app_id
    app_id="$PACKAGE_NAME"
    
    # Check if device is connected
    if ! adb devices | grep -q "device\|emulator"; then
        echo "ERROR:" "No Android device/emulator connected"
        return 1
    fi
    
    # Check if app is already installed
    if adb shell pm list packages | grep -q "$app_id"; then
        echo "App is already installed: $app_id"
        
        # Check if APK exists and is newer than installed version
        local apk_path="$SCRIPT_DIR/apk/simplelogin-fdroid-release.apk"
        if [[ -f "$apk_path" ]]; then
            echo "APK already built - skipping rebuild"
            return 0
        else
            echo "APK not found - rebuilding..."
        fi
    else
        echo "App not installed - will build and install"
    fi
    
    # Check if APK exists (should be built by setup_app_source.sh first)
    local apk_path="$SCRIPT_DIR/apk/simplelogin-fdroid-release.apk"
    if [[ ! -f "$apk_path" ]]; then
        echo "ERROR:" "APK not found at $apk_path"
        echo "Please run setup_app_source.sh first to build the APK."
        return 1
    fi
    
    echo "Installing APK: $apk_path"
    
    # Uninstall any existing version
    adb uninstall "$app_id" >/dev/null 2>&1 || true
    
    # Install the APK
    if ! adb install "$apk_path"; then
        echo "ERROR:" "APK installation failed"
        return 1
    fi
    
    echo "App build and installation completed"
}

smoke_test() {
    echo "Running smoke test..."
    
    local app_id
    app_id="$PACKAGE_NAME"
    
    # Launch app
    echo "Launching app..."
    adb shell monkey -p "$app_id" -c android.intent.category.LAUNCHER 1 > /dev/null 2>&1
    
    # Wait for app to start
    sleep 5
    
    # Check if app is running
    if adb shell pidof "$app_id" > /dev/null 2>&1; then
        echo "App is running"
    else
        echo "Warning: App launch verification failed"
    fi
    
    echo "Smoke test completed"
}

verify_setup() {
    echo "Verifying complete setup..."
    
    # Check backend health
    if curl -s "http://localhost:7777/" > /dev/null; then
        echo "Backend API is responding"
    else
        echo "ERROR:" "Backend API is not responding"
        return 1
    fi
    
    # Check app installation
    local app_id
    app_id="$PACKAGE_NAME"
    
    if adb shell pm list packages | grep -q "$app_id"; then
        echo "App is installed on device"
    else
        echo "ERROR:" "App is not installed on device"
        return 1
    fi
    
    # Check secrets file
    if [[ -f "$SECRETS_FILE" ]]; then
        echo "Secrets file created"
    else
        echo "ERROR:" "Secrets file not found"
        return 1
    fi
    
    echo "Setup verification completed"
}




ensure_submodule_ready() {
    echo "Ensuring submodule is ready..."
    
    # Sync and update submodules
    git submodule sync --recursive
    git submodule update --init --recursive --checkout codebase
    
    # Check if codebase directory exists
    if [[ ! -d "$SCRIPT_DIR/codebase" ]]; then
        echo "ERROR:" "Failed to initialize codebase submodule"
        return 1
    fi
    
    # Get target commit from metadata
    local target_commit
    target_commit="$COMMIT_VERSION"
    
    if [[ "$target_commit" != "null" && -n "$target_commit" ]]; then
        echo "Checking out commit: $target_commit"
        cd "$SCRIPT_DIR/codebase"
        git checkout "$target_commit"
        cd "$SCRIPT_DIR"
    fi
    
    echo "Submodule ready at: $SCRIPT_DIR/codebase"
}

main() {
    echo "Starting SimpleLogin MobileCybench setup..."
    
    # Ensure submodule is initialized and at correct commit
    ensure_submodule_ready
    
    check_prerequisites
    setup_backend
    seed_test_data
    build_and_install_app
    smoke_test
    verify_setup
    
    echo "SimpleLogin MobileCybench setup completed successfully!"
    echo "Backend API: http://localhost:7777"
    echo "Secrets file: $SECRETS_FILE"
    echo "Ready for CIAA testing!"
}

# Cleanup function for interrupts
cleanup() {
    echo "Warning:" "Setup interrupted. Cleaning up..."
    cd "$SCRIPT_DIR"
    $DC down 2>/dev/null || true
    exit 1
}

trap cleanup INT TERM

# Run main function if script is executed directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
