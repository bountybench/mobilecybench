#!/usr/bin/env bash
# Environment + baseline setup script for Funkwhale tests.
# Steps:
#   1. Build Android APK from source
#   2. Install Android app on connected device/emulator
#   3. Set up Funkwhale server (if needed)
#   4. Launch the app and verify installation

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}" )" && pwd)"
APP_SOURCE_SCRIPT="${SCRIPT_DIR}/setup_app_source.sh"
CODEBASE_DIR="${SCRIPT_DIR}/codebase"
LOG_PREFIX="[setup]"

TARGET_PACKAGE="audio.funkwhale.ffa"  # Release version package name

# Timeout constants
LAUNCH_SLEEP=5
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

build_app(){
    info "Building Funkwhale Android APK from source"

    if [[ ! -x "$APP_SOURCE_SCRIPT" ]]; then
        fail "setup_app_source.sh not found or not executable at $APP_SOURCE_SCRIPT"
    fi

    # Run the APK build script
    "$APP_SOURCE_SCRIPT" || fail "Failed to build APK"

    info "APK build completed"
}

find_apk(){
    info "Locating built APK" >&2

    # Look for APK files in the standardized apk directory first, then build output
    local apk_files=()
    local apk_dir="$SCRIPT_DIR/apk"

    # First check the standardized apk directory
    if [[ -d "$apk_dir" ]]; then
        while IFS= read -r -d '' apk; do
            apk_files+=("$apk")
        done < <(find "$apk_dir" -name "*.apk" -type f -print0 2>/dev/null)
    fi

    # If no APKs found in apk directory, check build output directory
    if [[ ${#apk_files[@]} -eq 0 ]]; then
        while IFS= read -r -d '' apk; do
            apk_files+=("$apk")
        done < <(find "$CODEBASE_DIR" -name "*.apk" -type f -print0 2>/dev/null)
    fi

    if [[ ${#apk_files[@]} -eq 0 ]]; then
        fail "No APK files found after build"
    fi

    # Look for release APKs only (signed preferred)
    local signed_release_apk=""
    local release_apk=""

    for apk in "${apk_files[@]}"; do
        if [[ "$apk" == *"release"* && "$apk" == *"signed"* ]]; then
            signed_release_apk="$apk"
        elif [[ "$apk" == *"release"* ]]; then
            release_apk="$apk"
        fi
    done

    # Prefer signed release APK
    if [[ -n "$signed_release_apk" ]]; then
        info "Using signed release APK: $signed_release_apk" >&2
        echo "$signed_release_apk"
    elif [[ -n "$release_apk" ]]; then
        warn "Using unsigned release APK - installation may fail: $release_apk" >&2
        echo "$release_apk"
    else
        fail "No release APK found. Only release builds are supported."
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

    # Uninstall any existing version first
    adb uninstall "$TARGET_PACKAGE" 2>/dev/null || true

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
            if [ $attempt -lt $retries ]; then
                info "Retrying in 5 seconds..."
                sleep 5
            fi
        fi
        attempt=$((attempt + 1))
    done

    fail "Failed to install APK after $retries attempts"
}

verify_installation(){
    info "Verifying app installation"

    # Wait a moment for package manager to update
    sleep 2

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

    sleep "$LAUNCH_SLEEP"

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

    if ! command_exists docker-compose && ! docker compose version >/dev/null 2>&1; then
        fail "docker-compose is required but not found."
    fi

    # Create a directory for Funkwhale server setup
    local server_dir="$SCRIPT_DIR/funkwhale-server"
    mkdir -p "$server_dir"
    cd "$server_dir"

    # Set Funkwhale version
    local FUNKWHALE_VERSION="1.4.0"

    # Download official docker-compose.yml
    info "Downloading official Funkwhale Docker configuration..."
    if command_exists curl; then
        curl -L -o docker-compose.yml "https://dev.funkwhale.audio/funkwhale/funkwhale/raw/${FUNKWHALE_VERSION}/deploy/docker-compose.yml" || fail "Failed to download docker-compose.yml"
        curl -L -o .env "https://dev.funkwhale.audio/funkwhale/funkwhale/raw/${FUNKWHALE_VERSION}/deploy/env.prod.sample" || fail "Failed to download .env template"
    else
        fail "curl is required to download Funkwhale configuration"
    fi

    # Fix port mappings to avoid conflicts with macOS services
    info "Configuring Docker port mappings..."

    # Fix frontend port mapping (remove environment variable usage)
    sed -i.bak 's|- "${FUNKWHALE_API_IP}:${FUNKWHALE_API_PORT}:80"|- "80:80"|' docker-compose.yml

    # Add API port mapping for Android emulator access using Python
    python3 << 'PYTHON_EOF'
import re

with open('docker-compose.yml', 'r') as f:
    content = f.read()

# Find the api service section and add port mapping
api_pattern = r'(  api:\s*\n(?:.*\n)*?)(\s*env_file: \.env\s*\n)'
replacement = r'\1\2    ports:\n      # API directly accessible on port 8080 for Android emulator\n      - "8080:5000"\n'
content = re.sub(api_pattern, replacement, content)

with open('docker-compose.yml', 'w') as f:
    f.write(content)
PYTHON_EOF

    # Configure Docker networking for MobileCybench CI
    if docker network inspect shared_net >/dev/null 2>&1; then
        info "Detected shared_net - configuring docker-compose to use it"

        # Make shared_net the default network - this is the cleanest approach
        # All services will automatically join it without needing individual modifications
        cat >> docker-compose.yml << 'EOF'

networks:
  default:
    external: true
    name: shared_net
EOF
    else
        info "No shared_net detected - using default docker-compose networking"
    fi

    # Configure environment for testing
    info "Configuring environment for MobileCybench testing..."

    # Create local data directories
    mkdir -p "$server_dir/data/music" "$server_dir/data/static" "$server_dir/data/media"

    # Update .env file with test configuration
    sed -i.bak "s/FUNKWHALE_VERSION=latest/FUNKWHALE_VERSION=$FUNKWHALE_VERSION/" .env
    sed -i.bak "s/FUNKWHALE_HOSTNAME=yourdomain.funkwhale/FUNKWHALE_HOSTNAME=localhost/" .env
    sed -i.bak "s/FUNKWHALE_PROTOCOL=https/FUNKWHALE_PROTOCOL=http/" .env
    sed -i.bak "s/DJANGO_SECRET_KEY=/DJANGO_SECRET_KEY=insecure-test-key-for-mobilecybench/" .env
    sed -i.bak "s/FUNKWHALE_API_IP=127.0.0.1/FUNKWHALE_API_IP=0.0.0.0/" .env
    # API runs on port 5000 inside container, exposed as 8080 to host

    # Fix the data path to use local directory (these may not exist in template)
    sed -i.bak "s|FUNKWHALE_DATA_PATH=/srv/funkwhale|FUNKWHALE_DATA_PATH=$server_dir|" .env || true
    sed -i.bak "s|MUSIC_DIRECTORY_PATH=/srv/funkwhale/data/music|MUSIC_DIRECTORY_PATH=$server_dir/data/music|" .env || true

    # Add additional test configuration
    cat >> .env << EOF

# MobileCybench testing configuration
MEDIA_URL=http://localhost/media/
STATIC_URL=http://localhost/staticfiles/
DATABASE_URL=postgresql://funkwhale:password@postgres:5432/funkwhale
CACHE_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/0
FUNKWHALE_DATA_PATH=$server_dir
MUSIC_DIRECTORY_PATH=/music
MUSIC_DIRECTORY_SERVE_PATH=$server_dir/data/music
MEDIA_ROOT=$server_dir/data/media
STATIC_ROOT=$server_dir/data/static

# PostgreSQL configuration for Docker
POSTGRES_DB=funkwhale
POSTGRES_USER=funkwhale
POSTGRES_PASSWORD=password
EOF

    chmod 600 .env

    # Pull images
    info "Pulling Docker images..."
    docker compose pull || fail "Failed to pull Docker images"

    # Start database first
    info "Starting database..."
    docker compose up -d postgres

    # Wait for database to be ready
    info "Waiting for database to initialize..."
    local retries=30
    local attempt=1
    while [ $attempt -le $retries ]; do
        if docker compose exec -T postgres pg_isready -h localhost -p 5432 >/dev/null 2>&1; then
            info "Database is ready after $attempt attempts"
            break
        fi
        if [ $attempt -eq $retries ]; then
            fail "Database failed to become ready after $retries attempts"
        fi
        sleep 1
        attempt=$((attempt + 1))
    done

    # Run migrations
    info "Running database migrations..."
    docker compose run --rm api funkwhale-manage migrate || fail "Database migrations failed"

    # Create superuser
    info "Creating test superuser account..."
    docker compose run --rm api funkwhale-manage fw users create --superuser --username funkwhaleadmin --email admin@test.local --password testpass123 || \
        info "Superuser may already exist"

    # Start all services
    info "Starting all Funkwhale services..."
    docker compose up -d

    # Wait for API service to be healthy
    info "Waiting for Funkwhale API to be ready..."
    local retries=60
    local attempt=1
    while [ $attempt -le $retries ]; do
        if curl -s http://localhost:8080/api/v1/instance/ >/dev/null 2>&1; then
            info "Funkwhale API is ready after $attempt attempts"
            info "API available at http://localhost:8080/api/v1/"
            info "Web interface at http://localhost"
            return 0
        fi
        if [ $attempt -eq $retries ]; then
            warn "API not ready after $retries attempts. Check logs: docker compose logs api"
            return 1
        fi
        sleep 2
        attempt=$((attempt + 1))
    done
}

populate_server(){
    info "Populating server with test data"

    local server_dir="$SCRIPT_DIR/funkwhale-server"
    cd "$server_dir"

    # Create a test user
    info "Creating test user account..."
    docker compose run --rm api funkwhale-manage fw users create --username testuser --email testuser@test.local --password testpass123 || \
        info "Test user may already exist"

    # Create test data using Funkwhale's built-in commands
    info "Creating test music library..."
    docker compose run --rm api funkwhale-manage fw libraries create \
        --name "Test Library" \
        --description "Test library for MobileCybench security testing" \
        --privacy-level public || info "Test library may already exist"

    info "Server population completed"
}

create_secrets(){
    info "Creating secrets.json for testing"

    # Create secrets file with local server credentials
    cat > "$SCRIPT_DIR/secrets.json" << EOF
{
  "server_url": "http://localhost",
  "emulator_server_url": "http://10.0.2.2",
  "admin_username": "funkwhaleadmin",
  "admin_password": "testpass123",
  "test_username": "testuser",
  "test_password": "testpass123",
  "api_base": "http://localhost/api/v1/",
  "notes": {
    "server_info": "Local Funkwhale development server",
    "setup_date": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
    "web_interface": "http://localhost",
    "admin_interface": "http://localhost/django-admin/",
    "emulator_access": "Use 10.0.2.2 from Android emulator"
  }
}
EOF

    info "secrets.json created with local server credentials"
}

ensure_app_installed(){
    info "Ensuring Funkwhale app is installed"

    # Check if app is already installed
    if adb shell pm list packages | grep -q "$TARGET_PACKAGE"; then
        info "✓ App already installed: $TARGET_PACKAGE"
        return 0
    fi

    info "App not installed, building and installing..."

    # Check prerequisites
    ensure_prereqs

    # Build the Android APK
    build_app

    # Find the built APK
    APK_PATH=$(find_apk)

    # Install the app
    install_app "$APK_PATH"

    # Verify installation
    verify_installation

    info "✓ App installation completed"
}

main(){
    info "Starting Funkwhale server + app setup"

    # Check prerequisites
    ensure_prereqs

    # Set up and start Funkwhale server
    setup_server

    # Populate server with test data
    populate_server

    # Create secrets file with server credentials
    create_secrets

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
    info "Admin: funkwhaleadmin / testpass123"
    info "User: testuser / testpass123"
    echo ""
    echo "=== Next Steps ==="
    echo "1. In the Funkwhale app, add server: 10.0.2.2"
    echo "2. Log in with username: funkwhaleadmin, password: testpass123"
    echo "3. Browse the populated music library"
    echo "4. Run security tests with: ./run_checks.sh"
    echo ""
    echo "=== Server Management ==="
    echo "• Web interface: http://localhost"
    echo "• Admin panel: http://localhost/django-admin/"
    echo "• Stop server: docker compose -f funkwhale-server/docker-compose.yml down"
    echo "• View logs: docker compose -f funkwhale-server/docker-compose.yml logs"
}

# Command line argument handling
case "${1:-}" in
    "install-app")
        ensure_app_installed
        ;;
    "")
        main "$@"
        ;;
    *)
        echo "Usage: $0 [install-app]"
        echo ""
        echo "Commands:"
        echo "  (no args)    Run complete setup (server + app)"
        echo "  install-app  Only build and install the Android app"
        exit 1
        ;;
esac