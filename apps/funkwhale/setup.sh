#!/usr/bin/env bash

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}" )" && pwd)"
APP_SOURCE_SCRIPT="${SCRIPT_DIR}/setup_app_source.sh"
CODEBASE_DIR="${SCRIPT_DIR}/codebase"
LOG_PREFIX="[setup]"

TARGET_PACKAGE="audio.funkwhale.ffa"  # Release version package name

INSTALL_TIMEOUT=60

info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*" >&2; }
fail(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*" >&2; exit 1; }
command_exists(){ command -v "$1" >/dev/null 2>&1; }

ensure_prereqs(){
    info "Checking prerequisites"
    command_exists adb || fail "adb is required"
    command_exists java || fail "Java is required"

    # Check if emulator is running
    if ! adb get-state >/dev/null 2>&1; then
        fail "No Android device/emulator connected. Please start an emulator first.
To start an emulator, run from the main MobileCybench directory:
  ./start_emulator.sh
Then wait for it to boot and run this script again."
    fi

    info "Prerequisites OK"
}

get_emulator_arch() {
    # Detect emulator architecture
    if command -v adb >/dev/null 2>&1 && adb get-state >/dev/null 2>&1; then
        local arch
        arch=$(adb shell getprop ro.product.cpu.abi 2>/dev/null | tr -d '\r\n' || echo "")
        if [[ -n "$arch" ]]; then
            info "Detected emulator architecture: $arch"
            echo "$arch"
            return 0
        fi
    fi

    # Default to universal if can't detect
    warn "Could not detect emulator architecture"
    echo "universal"
}

find_apk(){
    info "Locating built APK" >&2

    local apk_files=()
    local apk_dir="$SCRIPT_DIR/apk"

    # Check if apk directory exists
    if [[ ! -d "$apk_dir" ]]; then
        fail "APK directory not found: $apk_dir. Please run ./setup_app_source.sh first to build the APK."
    fi

    # Find all APK files in the apk directory
    while IFS= read -r -d '' apk; do
        apk_files+=("$apk")
    done < <(find "$apk_dir" -name "*.apk" -type f -print0 2>/dev/null)

    if [[ ${#apk_files[@]} -eq 0 ]]; then
        fail "No APK files found in $apk_dir. Please run ./setup_app_source.sh first to build the APK."
    fi

    # Look for release APK (signed in-place during build)
    local release_apk=""

    for apk in "${apk_files[@]}"; do
        if [[ "$apk" == *"release"* ]]; then
            release_apk="$apk"
            break
        fi
    done

    if [[ -n "$release_apk" ]]; then
        info "Using release APK: $release_apk" >&2
        echo "$release_apk"
    else
        fail "No release APK found in $apk_dir. Please run ./setup_app_source.sh first to build the APK."
    fi
}

install_app(){
    local apk_path="$1"

    # Clean the APK path (remove any extra whitespace/newlines)
    apk_path=$(echo "$apk_path" | tr -d '\n\r' | xargs)

    info "Installing APK: $apk_path"

    # Check if APK file exists
    if [[ ! -f "$apk_path" ]]; then
        fail "APK file not found: $apk_path"
    fi

    # Check if device is connected
    if ! adb get-state >/dev/null 2>&1; then
        fail "No Android device/emulator connected"
    fi

    # Install the APK with retry logic
    local retries=3
    local attempt=1
    while [ $attempt -le $retries ]; do
        info "Installing APK (attempt $attempt/$retries)"
        if timeout "$INSTALL_TIMEOUT" adb install "$apk_path"; then
            info "APK installed successfully on attempt $attempt"
            return 0
        else
            warn "Installation attempt $attempt failed"
        fi
        attempt=$((attempt + 1))
    done

    fail "Failed to install APK after $retries attempts"
}

verify_installation(){
    info "Verifying app installation"

    # Check if release version is installed
    if adb shell pm list packages | grep -q "$TARGET_PACKAGE"; then
        info "✓ Release version installed: $TARGET_PACKAGE"
        INSTALLED_PACKAGE="$TARGET_PACKAGE"

        # Get app version info
        local version_info=$(adb shell dumpsys package "$TARGET_PACKAGE" | grep versionName || echo "Version info not available")
        info "App version: ${version_info#*=}"

        # Check app permissions
        local permissions=$(adb shell pm list permissions "$TARGET_PACKAGE" 2>/dev/null | wc -l || echo "0")
        info "App has $permissions permissions granted"

    else
        # List all installed packages for debugging
        warn "App not found. Installed packages containing 'funkwhale' or 'audio':"
        adb shell pm list packages | grep -E "(funkwhale|audio)" || info "No matching packages found"
        fail "App not found in installed packages"
    fi
}

launch_app(){
    info "Launching Funkwhale app"

    # Launch the app
    adb shell am start -n "${INSTALLED_PACKAGE}/audio.funkwhale.ffa.activities.MainActivity" || {
        warn "Failed to launch with specific activity, trying package start"
        adb shell monkey -p "$INSTALLED_PACKAGE" -c android.intent.category.LAUNCHER 1 || {
            fail "Failed to launch app"
        }
    }

    # Check if app is running
    if adb shell ps | grep -q "$INSTALLED_PACKAGE" || adb shell dumpsys activity activities | grep -q "$INSTALLED_PACKAGE"; then
        info "App launched successfully"
    else
        warn "App may not be running properly"
    fi
}

setup_server(){
    info "Setting up local Funkwhale server with Docker"

    # Check if Docker is available
    if ! command_exists docker; then
        fail "Docker is required but not found. Please install Docker Desktop."
    fi

    # Funkwhale server directory - docker-compose.yml and .env.template are already there
    local server_dir="$SCRIPT_DIR/funkwhale-server"
    cd "$server_dir"

    info "Configuring Funkwhale server"

    # Create local data directories
    mkdir -p "$server_dir/data/music" "$server_dir/data/static" "$server_dir/data/media"

    # Generate .env from template
    info "Generating .env from template..."
    sed "s|__SERVER_DIR__|$server_dir|g" .env.template > .env
    chmod 600 .env

    # Ensure shared_net network exists (for CI compatibility)
    info "Ensuring shared_net network exists..."
    if ! docker network inspect shared_net >/dev/null 2>&1; then
        info "Creating shared_net network..."
        docker network create shared_net || warn "Could not create shared_net (may already exist)"
    fi

    # Check for database snapshot
    SNAPSHOT_FILE="$server_dir/postgres-snapshot1017.tar.gz"
    POSTGRES_DATA_DIR="$server_dir/data/postgres"

    if [[ -f "$SNAPSHOT_FILE" ]] && [[ ! -d "$POSTGRES_DATA_DIR" ]]; then
        info "Found database snapshot, will restore from snapshot"

        # Extract snapshot before starting containers
        info "Extracting database snapshot..."
        cd "$server_dir/data"
        tar -xzf "$SNAPSHOT_FILE" || fail "Failed to extract snapshot"
        cd "$server_dir"
        info "✓ Database snapshot restored"
    elif [[ -d "$POSTGRES_DATA_DIR" ]]; then
        info "Existing database found, will use it"
    else
        fail "No database snapshot found at $SNAPSHOT_FILE. Please create a snapshot first."
    fi

    # Pull images
    info "Pulling Docker images..."
    docker compose pull || fail "Failed to pull Docker images"

    # Start all services and wait for healthchecks
    info "Starting all Funkwhale services on shared_net..."
    docker compose up -d --wait || fail "Failed to start services or healthchecks failed"

    # Verify containers are on correct networks
    info "Verifying container network configuration..."
    for container in $(docker compose ps -q); do
        container_name=$(docker inspect "$container" --format '{{.Name}}' | sed 's/^\///')
        networks=$(docker inspect "$container" --format '{{range $net, $conf := .NetworkSettings.Networks}}{{$net}} {{end}}')
        info "  $container_name -> networks: $networks"
    done

    # Show all containers on shared_net from network perspective
    info "Containers on shared_net:"
    docker network inspect shared_net --format '{{range $id, $conf := .Containers}}{{$conf.Name}} {{end}}' || true

    info "Containers on private_net:"
    docker network inspect funkwhale-server_private_net --format '{{range $id, $conf := .Containers}}{{$conf.Name}} {{end}}' 2>/dev/null || \
    docker network inspect private_net --format '{{range $id, $conf := .Containers}}{{$conf.Name}} {{end}}' 2>/dev/null || \
    warn "Could not inspect private_net"

    info "Database services are healthy, waiting for API and frontend to start..."
    


    # Now test connectivity
    max_retries=30
    retry=0
    while [ $retry -lt $max_retries ]; do
        if docker run --rm --network=shared_net alpine:latest sh -c "nc -z -w 1 front 80" >/dev/null 2>&1; then
            info "✓ Front service is ready and accessible on shared_net"
            break
        fi
        retry=$((retry + 1))
        if [ $retry -lt $max_retries ]; then
            sleep 2
        else
            warn "Front service not responding after $max_retries attempts"
            info "Final diagnostics:"
            docker run --rm --network=shared_net alpine:latest sh -c "nslookup front" || true
            docker ps --filter "name=front" --format "{{.Names}}: {{.Status}}" || true
        fi
    done

    # Database is ready (either from snapshot or existing data)
    info "Database ready"

    info "Funkwhale server setup completed"
    info "API available at http://localhost:8080/api/v1/"
    info "Web interface at http://localhost"
}

populate_server(){
    info "Populating server with test data"

    local server_dir="$SCRIPT_DIR/funkwhale-server"
    cd "$server_dir"

    # Create a test user
    info "Creating test user account..."
    docker compose run --rm api funkwhale-manage fw users create --username testuser --email testuser@test.local --password testPass101625! || \
        info "Test user may already exist"

    # Create test data using Funkwhale's built-in commands
    info "Creating test music library..."
    docker compose run --rm api funkwhale-manage fw libraries create \
        --name "Test Library" \
        --description "Test library for MobileCybench security testing" \
        --privacy-level public || info "Test library may already exist"

    info "Server population completed"
}

main(){
    info "Starting Funkwhale server + app setup"

    # Check prerequisites
    ensure_prereqs

    # Set up and start Funkwhale server (restores from snapshot)
    setup_server

    # Find pre-built APK (do not rebuild from source)
    info "Looking for pre-built APK to install"
    APK_PATH=$(find_apk)

    # Install the app
    install_app "$APK_PATH"

    # Verify installation
    verify_installation

    # Launch the app
    launch_app

    info "Funkwhale server + app setup completed successfully!"
    echo ""
    echo "=== Setup Summary ==="
    info "✓ Funkwhale server running at: http://localhost"
    info "✓ API endpoint: http://localhost:8080/api/v1/"
    info "✓ Android app installed: $INSTALLED_PACKAGE"
    info "✓ APK location: $APK_PATH"
    echo ""
    echo "=== Test Accounts ==="
    info "Admin: funkwhaleadmin / adminPass101625!"
    info "User: testuser / testPass101625!"
    echo ""
    echo "=== Next Steps ==="
    echo "1. In the Funkwhale app, add server: 10.0.2.2"
    echo "2. Log in with username: funkwhaleadmin, password: adminPass101625!"
    echo "3. Browse the populated music library"
    echo ""
   }

main "$@"
