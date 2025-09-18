#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
METADATA_FILE="$SCRIPT_DIR/metadata.json"
SECRETS_FILE="$SCRIPT_DIR/secrets.json"

# Dynamic Docker Compose detection (v1/v2)
if docker compose version >/dev/null 2>&1; then
    DC="docker compose"
else
    DC="docker-compose"
fi

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
    
    # Check for docker compose (either v1 or v2)
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
    if adb devices | grep -q "emulator.*device"; then
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
    
    # Wait for services to be healthy
    echo "Waiting for backend services to be ready..."
    local timeout=60
    local counter=0
    
    while [[ $counter -lt $timeout ]]; do
        if $DC ps | grep -q "healthy"; then
            echo "Backend services are healthy"
            break
        fi
        
        if [[ $counter -ge $timeout ]]; then
            echo "ERROR:" "Timeout waiting for backend services"
            $DC logs
            return 1
        fi
        
        echo "Waiting for services... ($counter/$timeout)"
        sleep 2
        ((counter++))
    done
    
    # Wait for API HTTP readiness (expect 302 redirect)
    echo "Waiting for API HTTP readiness..."
    for i in {1..60}; do
        if curl -fsS -o /dev/null -w "%{http_code}" "http://localhost:7777/" | grep -q "302"; then
            echo "API is answering HTTP requests (302 redirect)"
            break
        fi
        if [[ $i -eq 60 ]]; then
            echo "ERROR:" "Timeout waiting for API HTTP readiness"
            return 1
        fi
        sleep 2
    done
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
    if ! adb devices | grep -q "device$"; then
        echo "ERROR:" "No Android device/emulator connected"
        return 1
    fi
    
    # Check if app is already installed
    if adb shell pm list packages | grep -q "$app_id"; then
        echo "App is already installed: $app_id"
        
        # Check if APK exists and is newer than installed version
        local apk_path="$SCRIPT_DIR/codebase/SimpleLogin/app/build/outputs/apk/fdroid/debug/app-fdroid-debug.apk"
        if [[ -f "$apk_path" ]]; then
            echo "APK already built, checking if installation is current..."
            
            # Get installed version
            local installed_version
            installed_version=$(adb shell dumpsys package "$app_id" | grep "versionCode" | head -1 | cut -d'=' -f2 | tr -d ' ' || echo "")
            
            # Get APK version (simplified - just check if APK exists and is recent)
            local apk_age
            apk_age=$(find "$apk_path" -mtime -1 2>/dev/null && echo "recent" || echo "old")
            
            if [[ "$apk_age" == "recent" ]]; then
                echo "APK is recent and app is installed - skipping rebuild"
                return 0
            else
                echo "APK is outdated - rebuilding..."
            fi
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
    
    # Find and install the built APK
    local apk_path="$SCRIPT_DIR/codebase/SimpleLogin/app/build/outputs/apk/fdroid/debug/app-fdroid-debug.apk"
    
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
    adb shell am start -n "$app_id/.MainActivity" 2>/dev/null || \
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
