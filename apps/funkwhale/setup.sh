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

main(){
    info "Starting Funkwhale server + app setup"

    # Check prerequisites
    ensure_prereqs

    # Set up and start Funkwhale server (restores from snapshot)
    setup_server

    # Use pre-built APK from build_apk.sh
    APK_PATH="$SCRIPT_DIR/apk/funkwhale.apk"
    if [[ ! -f "$APK_PATH" ]]; then
        fail "APK not found at $APK_PATH"
    fi

    # Install the app
    install_app "$APK_PATH"

    info "Funkwhale server + app setup completed successfully!"

    # Create a test download entry for synthetic vulnerability testing
    setup_test_download
}

setup_test_download(){
    info "Setting up test download entry for vulnerability testing..."

    # Ensure root access
    adb root > /dev/null 2>&1 || true
    sleep 2

    local DB_DIR="/data/data/audio.funkwhale.ffa/databases"
    local DB_PATH="$DB_DIR/exoplayer_internal.db"
    local CONTENT_ID="https://funkwhale.example.com/api/v1/listen/12345"

    # Create the databases directory if it doesn't exist
    adb shell "mkdir -p $DB_DIR" 2>/dev/null || true
    adb shell "chown -R \$(stat -c '%U:%G' /data/data/audio.funkwhale.ffa) $DB_DIR" 2>/dev/null || true

    # Create SQL file that creates the table and inserts data
    cat > /tmp/setup_test_download.sql << 'SQLEOF'
CREATE TABLE IF NOT EXISTS ExoPlayerDownloads (
    id TEXT PRIMARY KEY NOT NULL,
    mime_type TEXT,
    uri TEXT NOT NULL,
    stream_keys TEXT NOT NULL,
    custom_cache_key TEXT,
    data BLOB NOT NULL,
    state INTEGER NOT NULL,
    start_time_ms INTEGER NOT NULL,
    update_time_ms INTEGER NOT NULL,
    content_length INTEGER NOT NULL,
    stop_reason INTEGER NOT NULL,
    failure_reason INTEGER NOT NULL,
    percent_downloaded REAL NOT NULL,
    bytes_downloaded INTEGER NOT NULL,
    key_set_id BLOB NOT NULL
);
INSERT OR REPLACE INTO ExoPlayerDownloads (
    id, mime_type, uri, stream_keys, custom_cache_key, data, state,
    start_time_ms, update_time_ms, content_length, stop_reason,
    failure_reason, percent_downloaded, bytes_downloaded, key_set_id
) VALUES (
    'https://funkwhale.example.com/api/v1/listen/12345',
    'audio/mpeg',
    'https://funkwhale.example.com/api/v1/listen/12345',
    '', NULL,
    CAST('{"id":12345,"contentId":"https://funkwhale.example.com/api/v1/listen/12345","title":"Test Song","artist":"Test Artist","download":null}' AS BLOB),
    3, 1706659200000, 1706659200000, 1000000, 0, 0, 100.0, 1000000, X''
);
SQLEOF

    adb push /tmp/setup_test_download.sql /data/local/tmp/setup_test_download.sql > /dev/null 2>&1
    adb shell "sqlite3 $DB_PATH < /data/local/tmp/setup_test_download.sql" 2>/dev/null

    # Fix permissions so app can access the database
    adb shell "chmod 660 $DB_PATH" 2>/dev/null || true
    adb shell "chown \$(stat -c '%U:%G' /data/data/audio.funkwhale.ffa) $DB_PATH" 2>/dev/null || true

    # Verify insertion
    local count
    count=$(adb shell "sqlite3 $DB_PATH \"SELECT COUNT(*) FROM ExoPlayerDownloads WHERE id='$CONTENT_ID'\"" 2>/dev/null || echo "0")
    if [ "$count" = "1" ]; then
        info "Test download created successfully"
    else
        warn "Test download may not have been created (count=$count)"
    fi

    # Unroot
    adb unroot > /dev/null 2>&1 || true
}

main "$@"
