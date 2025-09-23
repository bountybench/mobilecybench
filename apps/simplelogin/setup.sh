#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
METADATA_FILE="$SCRIPT_DIR/metadata.json"
SECRETS_FILE="$SCRIPT_DIR/secrets.json"

# Use modern Docker Compose v2
DC="docker compose"

echo "Installing required Python packages..."
pip3 install requests uiautomator2 psycopg2-binary bcrypt 2>/dev/null || {
    echo "Warning: Some packages failed to install, trying individual installation..."
    pip3 install requests uiautomator2 bcrypt 2>/dev/null || pip3 install requests uiautomator2
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

setup_emulator() {
    echo "Setting up Android emulator..."
    
    # Check if emulator is already running
    if adb devices | grep -q "device\|emulator"; then
        echo "Emulator already running"
        return 0
    fi
    
    # Start emulator (assuming avd name is 'test_avd' - adjust as needed)
    local avd_name="test_avd"
    
    # List available AVDs
    local avd_list
    avd_list=$(emulator -list-avds 2>/dev/null || echo "")
    
    if [[ -z "$avd_list" ]]; then
        echo "ERROR:" "No Android Virtual Devices found. Please create an AVD."
        return 1
    fi
    
    # Use the first available AVD
    avd_name=$(echo "$avd_list" | head -1)
    echo "Starting emulator with AVD: $avd_name"
    
    # Start emulator in background
    emulator -avd "$avd_name" -no-audio -no-window &
    local emulator_pid=$!
    
    # Wait for emulator to boot
    echo "Waiting for emulator to boot..."
    adb wait-for-device
    
    # Wait for system to be ready
    while [[ "$(adb shell getprop sys.boot_completed 2>/dev/null)" != "1" ]]; do
        echo "Waiting for system boot to complete..."
        sleep 5
    done
    
    echo "Emulator is ready"
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
    
    # Note: shared_net is now created by docker-compose automatically
    
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
    echo "Generating test credentials and seeding data..."
    
    # Use generate_secrets.py for reliable credential generation
    if python3 generate_secrets.py --create-user --verbose; then
        echo "Secrets generation and user creation completed"
    else
        echo "Warning:" "generate_secrets.py failed, trying fallback authentication..."
        # Fallback to simplelogin_login.py if generate_secrets fails
        if python3 simplelogin_login.py --register --activate --login --create-secrets --verbose; then
            echo "Fallback authentication completed"
        else
            echo "ERROR: Both secrets generation methods failed"
            return 1
        fi
    fi
}

build_and_install_app() {
    echo "Building and installing SimpleLogin app..."
    
    # Check if app is already installed and up-to-date
    local app_id
    app_id=$(jq -r '.app_id' "$METADATA_FILE")
    
    # Check if device is connected
    if ! adb devices | grep -q "device\|emulator"; then
        echo "ERROR:" "No Android device/emulator connected"
        return 1
    fi
    
    # Check if app is already installed
    if adb shell pm list packages | grep -q "$app_id"; then
        echo "App is already installed: $app_id"
        
        # Check if APK exists and is newer than installed version
        local apk_path="$SCRIPT_DIR/codebase/SimpleLogin/app/build/outputs/apk/fdroid/debug/app-fdroid-debug.apk"
        if [[ -f "$apk_path" ]]; then
            echo "APK already built - skipping rebuild"
            return 0
        else
            echo "APK not found - rebuilding..."
        fi
    else
        echo "App not installed - will build and install"
    fi
    
    # Check if codebase directory exists
    if [[ ! -d "$SCRIPT_DIR/codebase" ]]; then
        echo "ERROR:" "Codebase directory not found. This may indicate a cleanup issue."
        echo "Please ensure the submodule is properly initialized."
        return 1
    fi
    
    # Run the app source setup script to build APK
    if ! bash "$SCRIPT_DIR/setup_app_source.sh"; then
        echo "ERROR:" "App build failed"
        return 1
    fi
    
    # Get APK path from build process
    local apk_path
    if [[ -f "$SCRIPT_DIR/apk_path.txt" ]]; then
        apk_path=$(cat "$SCRIPT_DIR/apk_path.txt")
    else
        echo "ERROR:" "APK path not found. Did the build succeed?"
        return 1
    fi
    
    if [[ ! -f "$apk_path" ]]; then
        echo "ERROR:" "Built APK not found at $apk_path"
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
    app_id=$(jq -r '.app_id' "$METADATA_FILE")
    
    # Launch app
    echo "Launching app..."
    adb shell monkey -p "$app_id" -c android.intent.category.LAUNCHER 1 > /dev/null 2>&1
    
    # Wait for app to start
    sleep 5
    
    # Check if app is running
    if adb shell pidof "$app_id" > /dev/null 2>&1; then
        echo "App is running"
    else
        echo "Warning:" "App launch verification failed"
    fi
    
    # Basic UI test - try to find login elements
    echo "Checking for login UI elements..."
    local ui_dump
    ui_dump=$(adb shell uiautomator dump --compressed /dev/stdout 2>/dev/null || echo "")
    
    if [[ "$ui_dump" =~ (email|login|password) ]]; then
        echo "Login UI elements detected"
    else
        echo "Warning:" "Login UI elements not clearly detected"
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
    app_id=$(jq -r '.app_id' "$METADATA_FILE")
    
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

# Configure API URL without source edits.
# Primary path: use adb root (available on most emulator images) to write SharedPreferences.
# Hard gate: verify API_URL presence after write.
configure_api_url() {
    echo "Configuring API URL via device preferences..."
    local app_id
    app_id=$(jq -r '.app_id' "$METADATA_FILE")
    local api_url
    api_url=$(jq -r '.emulator_server' "$METADATA_FILE")
    # Fallback if empty in metadata
    if [[ -z "$api_url" || "$api_url" == "null" ]]; then
        api_url="http://10.0.2.2:7777"
    fi

    # Ensure device ready
    adb wait-for-device

    # Try adb root (preferred, deterministic on emulator)
    if adb root >/dev/null 2>&1; then
        local pref_dir="/data/data/$app_id/shared_prefs"
        local pref_file="io.simplelogin.android.xml"
        # Write minimal prefs with API_URL only (non-destructive for runtime)
        adb shell "mkdir -p $pref_dir && cat > $pref_dir/$pref_file" <<EOF
<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
  <string name="API_URL">$api_url</string>
  <boolean name="FORCE_DARK_MODE" value="false" />
  <boolean name="SHOULD_LOCALLY_AUTHENTICATE" value="false" />
</map>
EOF
        # Best-effort permissions; UID varies, chmod is sufficient for app to read
        adb shell "chmod 600 $pref_dir/$pref_file" >/dev/null 2>&1 || true
        adb shell am force-stop "$app_id" || true

        # Hard verification gate: ensure key present
        if adb shell run-as "$app_id" grep -q "API_URL" "$pref_dir/$pref_file"; then
            echo "API URL pref set to $api_url"
            return 0
        else
            echo "ERROR: API_URL not found after write"
            return 1
        fi
    else
        echo "adb root not available; skip device-side write (UI automation required)"
        return 1
    fi
}

# UI automation: set API URL via on-screen controls (no source edits, F-Droid package).
# Gate A: action completes (we could detect by presence of key or proceeding to next step without errors).
# Gate B: force-stop app to reload prefs.
configure_api_url_ui() {
    echo "Configuring API URL via UI automation (uiautomator2)..."
    local app_id api_url
    app_id=$(jq -r '.app_id' "$METADATA_FILE")
    api_url=$(jq -r '.emulator_server' "$METADATA_FILE")
    if [[ -z "$api_url" || "$api_url" == "null" ]]; then
        api_url="http://10.0.2.2:7777"
    fi
    # Ensure uiautomator2 dependency is present
    pip3 show uiautomator2 >/dev/null 2>&1 || pip3 install --quiet uiautomator2 || true
    # Run the Python UI automation script
    if python3 "$SCRIPT_DIR/uiauto_set_api_url.py" --url "$api_url" --pkg "$app_id"; then
        # Gate B: force-stop to reload
        adb shell am force-stop "$app_id" || true
        # Gate A verify (best-effort)
        local pref_dir="/data/data/$app_id/shared_prefs"
        if adb shell run-as "$app_id" grep -q "API_URL" "$pref_dir/io.simplelogin.android.xml" 2>/dev/null; then
            echo "UI automation set API_URL successfully"
            return 0
        fi
        echo "Warning: UI succeeded but could not confirm API_URL key; proceeding"
        return 0
    fi
    echo "UI automation failed"
    return 1
}

# Wrapper: prefer UI automation; fallback to adb-root based seeding when available.
configure_api_url_any() {
    if configure_api_url_ui; then
        echo "Configured API URL via UI automation"
        return 0
    fi
    echo "UI automation failed or not available; trying adb-root fast path"
    if configure_api_url; then
        echo "Configured API URL via adb-root fast path"
        return 0
    fi
    echo "ERROR: Could not configure API URL via UI or adb-root"
    return 1
}

# Best-effort check for cleartext policy; if disabled, recommend HTTPS backend.
check_cleartext_policy() {
    echo "Checking app cleartext traffic policy (best-effort)..."
    local app_id
    app_id=$(jq -r '.app_id' "$METADATA_FILE")
    # Try to detect via dumpsys (may not expose flag reliably). Non-fatal.
    if adb shell dumpsys package "$app_id" | grep -iq "usesCleartextTraffic=false"; then
        echo "Warning: App may disallow cleartext HTTP. Consider using HTTPS for emulator_server."
    else
        echo "Cleartext policy not found or allowed; proceeding."
    fi
}

# Best-effort runtime verification that app attempts to talk to configured backend.
verify_network_to_backend() {
    echo "Verifying network to backend (best-effort)..."
    local app_id
    app_id=$(jq -r '.app_id' "$METADATA_FILE")
    local api_url
    api_url=$(jq -r '.emulator_server' "$METADATA_FILE")
    if [[ -z "$api_url" || "$api_url" == "null" ]]; then
        api_url="http://10.0.2.2:7777"
    fi
    local host_port
    host_port=$(echo "$api_url" | sed -E 's#^[a-zA-Z]+://([^/]+).*#\1#')

    # Clear existing logs, launch app, wait briefly, then scan logcat for host/port hints.
    adb logcat -c || true
    adb shell monkey -p "$app_id" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
    sleep 3
    if adb logcat -d | grep -E "${host_port//./\\.}" >/dev/null 2>&1; then
        echo "Detected references to $host_port in logcat; network likely configured."
        return 0
    fi
    echo "Warning: Could not confirm app network to $host_port via logcat (non-fatal)."
    return 0
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
    target_commit=$(jq -r '.commit_version' "$METADATA_FILE")
    
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
    setup_emulator
    setup_backend
    seed_test_data
  build_and_install_app
  configure_api_url_any || { echo "ERROR: Failed to configure API URL"; exit 1; }
  check_cleartext_policy || true
  verify_network_to_backend || true
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
