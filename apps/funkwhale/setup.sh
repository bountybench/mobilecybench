#!/usr/bin/env bash

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}" )" && pwd)"

TARGET_PACKAGE="audio.funkwhale.ffa"  # Release version package name

INSTALL_TIMEOUT=60

info(){ printf '%s %s\n' "[setup]" "$*"; }
warn(){ printf '%s[warn] %s\n' "[setup]" "$*" >&2; }
fail(){ printf '%s[error] %s\n' "[setup]" "$*" >&2; exit 1; }
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

verify_ssl_certificates(){
    local server_dir="$1"

    info "Verifying SSL certificates for HTTPS server"

    # Check if SSL directory exists
    if [[ ! -d "$server_dir/ssl" ]]; then
        fail "SSL directory not found: $server_dir/ssl
Please run ./setup_app_source.sh first to generate SSL certificates and build the APK.
The certificates must be generated before building the app so they can be embedded in the APK."
    fi

    # Check if certificates exist
    if [[ ! -f "$server_dir/ssl/server.crt" ]]; then
        fail "SSL certificate not found: $server_dir/ssl/server.crt
Please run ./setup_app_source.sh first to generate SSL certificates and build the APK.
The certificates must be generated before building the app so they can be embedded in the APK."
    fi

    if [[ ! -f "$server_dir/ssl/server.key" ]]; then
        fail "SSL private key not found: $server_dir/ssl/server.key
Please run ./setup_app_source.sh first to generate SSL certificates and build the APK.
The certificates must be generated before building the app so they can be embedded in the APK."
    fi

    # Verify certificate is for the correct hostname (10.0.2.2)
    local cert_cn=$(openssl x509 -noout -subject -in "$server_dir/ssl/server.crt" 2>/dev/null | grep -o "CN.*" | cut -d= -f2 | tr -d ' ')

    if [[ "$cert_cn" != "10.0.2.2" ]]; then
        warn "Certificate CN is '$cert_cn', expected '10.0.2.2'"
        warn "This may cause SSL connection issues from the Android emulator"
    else
        info "✓ SSL certificate CN verified: $cert_cn"
    fi

    # Show certificate expiration
    local expiry=$(openssl x509 -noout -enddate -in "$server_dir/ssl/server.crt" 2>/dev/null | cut -d= -f2)
    info "Certificate expires: $expiry"

    info "✓ SSL certificates verified and ready for HTTPS"
    return 0
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

    # Create local data directories (only for items not using named volumes)
    mkdir -p "$server_dir/data/music" "$server_dir/data/static" "$server_dir/data/media"

    # Generate .env from template
    info "Generating .env from template..."
    sed "s|__SERVER_DIR__|$server_dir|g" .env.template > .env
    chmod 600 .env

    # Verify SSL certificates exist (generated by setup_app_source.sh)
    verify_ssl_certificates "$server_dir"

    # nginx.conf is already configured for HTTPS (committed in repo)
    # No need to recreate it

    # Ensure shared_net network exists (for CI compatibility)
    info "Ensuring shared_net network exists..."
    if ! docker network inspect shared_net >/dev/null 2>&1; then
        info "Creating shared_net network..."
        docker network create shared_net || warn "Could not create shared_net (may already exist)"
    fi

    # Check for database snapshot
    SNAPSHOT_FILE="$server_dir/postgres-snapshot1017.tar.gz"
    VOLUME_NAME="funkwhale-server_postgres_data"

    # Check if volume already has data (volume exists and postgres started before)
    if docker volume inspect "$VOLUME_NAME" >/dev/null 2>&1; then
        info "Postgres volume already exists, will use existing data"
    elif [[ -f "$SNAPSHOT_FILE" ]]; then
        info "Restoring database from snapshot using postgres container..."

        # Use postgres container to extract snapshot into volume
        # Volume is created automatically on first use
        # Mount snapshot file into container and extract it
        docker compose run --rm --no-deps \
            -v "${SNAPSHOT_FILE}:/snapshot.tar.gz:ro" \
            postgres sh -c \
            "cd /var/lib/postgresql/data && tar -xzf /snapshot.tar.gz --strip-components=1" || \
            fail "Failed to restore database snapshot"

        info "✓ Database snapshot restored to volume"
    else
        fail "No database snapshot found at $SNAPSHOT_FILE. Please create a snapshot first."
    fi

    # Pull images
    info "Pulling Docker images..."
    docker compose pull || fail "Failed to pull Docker images"

    # Start all services and wait for healthchecks
    info "Starting all Funkwhale services on shared_net..."
    docker compose up -d --wait || fail "Failed to start services or healthchecks failed"

    info "Database services are healthy, waiting for API and frontend to start..."


    info "Funkwhale server setup completed"
    info "API available at https://localhost/api/v1/ (HTTPS)"
    info "Web interface at https://localhost (HTTPS)"
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

    info "Funkwhale server + app setup completed successfully!"
   }

main "$@"
