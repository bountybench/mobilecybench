#!/usr/bin/env bash

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}" )" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "funkwhale" "$@")

TARGET_PACKAGE="audio.funkwhale.ffa"

info(){ printf '%s %s\n' "[setup]" "$*"; }
warn(){ printf '%s[warn] %s\n' "[setup]" "$*" >&2; }
fail(){ printf '%s[error] %s\n' "[setup]" "$*" >&2; exit 1; }

setup_server(){
    info "Setting up local Funkwhale server with Docker"

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
    setup_server

    # Install the app
    adb_install_apk "$APK_PATH"

    info "Funkwhale server + app setup completed successfully!"
   }

main "$@"
