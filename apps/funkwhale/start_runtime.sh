#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "funkwhale" "$@")
cd "$SCRIPT_DIR"

TARGET_PACKAGE="audio.funkwhale.ffa"

setup_server(){
    log_info "Setting up local Funkwhale server with Docker"

    local server_dir="$SCRIPT_DIR/funkwhale-server"
    cd "$server_dir"

    log_info "Configuring Funkwhale server"

    mkdir -p "$server_dir/data/music" "$server_dir/data/static" "$server_dir/data/media"

    log_info "Generating .env from template..."
    sed "s|__SERVER_DIR__|$server_dir|g" .env.template > .env
    chmod 600 .env

    SNAPSHOT_FILE="$server_dir/postgres-snapshot1017.tar.gz"
    VOLUME_NAME="funkwhale-server_postgres_data"

    if docker volume inspect "$VOLUME_NAME" >/dev/null 2>&1; then
        log_info "Postgres volume already exists, will use existing data"
    elif [[ -f "$SNAPSHOT_FILE" ]]; then
        log_info "Restoring database from snapshot using postgres container..."

        docker compose run --rm --no-deps \
            -v "${SNAPSHOT_FILE}:/snapshot.tar.gz:ro" \
            postgres sh -c \
            "cd /var/lib/postgresql/data && tar -xzf /snapshot.tar.gz --strip-components=1" || \
            fatal "Failed to restore database snapshot"

        log_info "Database snapshot restored to volume"
    else
        fatal "No database snapshot found at $SNAPSHOT_FILE. Please create a snapshot first."
    fi

    log_info "Pulling Docker images..."
    docker compose pull || fatal "Failed to pull Docker images"

    log_info "Starting all Funkwhale services on shared_net..."
    docker compose up -d --wait || fatal "Failed to start services or healthchecks failed"

    log_info "Database services are healthy, waiting for API and frontend to start..."

    log_info "Funkwhale server setup completed"
    log_info "API available at https://localhost/api/v1/ (HTTPS)"
    log_info "Web interface at https://localhost (HTTPS)"
}

main(){
    log_info "Starting Funkwhale server + app setup"
    setup_server

    adb_install_apk "$APK_PATH"

    log_info "Funkwhale server + app setup completed successfully!"
}

main "$@"
