#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "funkwhale" "$@")
cd "$SCRIPT_DIR"

TARGET_PACKAGE="audio.funkwhale.ffa"

wait_for_docker(){
    for i in $(seq 1 30); do
        docker info >/dev/null 2>&1 && return 0
        log_info "Waiting for Docker daemon (attempt $i/30)..."
        sleep 2
    done
    fatal "Docker daemon did not become ready within 60 s"
}

setup_server(){
    local server_dir="$SCRIPT_DIR/funkwhale-server"
    cd "$server_dir"

    mkdir -p "$server_dir/data/music" "$server_dir/data/static" "$server_dir/data/media"

    log_info "Generating .env from template..."
    sed "s|__SERVER_DIR__|$server_dir|g" .env.template > .env
    chmod 600 .env

    local snapshot="$server_dir/postgres-snapshot1017.tar.gz"
    local volume="funkwhale-server_postgres_data"

    wait_for_docker

    if docker volume inspect "$volume" >/dev/null 2>&1; then
        log_info "Postgres volume already exists, will use existing data"
    elif [[ -f "$snapshot" ]]; then
        log_info "Restoring database from snapshot..."
        docker run --rm \
            -v "${volume}:/var/lib/postgresql/data" \
            -v "${snapshot}:/snapshot.tar.gz:ro" \
            postgres:15-alpine \
            sh -c "cd /var/lib/postgresql/data && tar -xzf /snapshot.tar.gz --strip-components=1" || \
            fatal "Failed to restore database snapshot"
    else
        fatal "No database snapshot found at $snapshot"
    fi

    log_info "Pulling Docker images..."
    docker compose pull || fatal "Failed to pull Docker images"

    log_info "Starting Funkwhale services..."
    docker compose up -d --wait || fatal "Failed to start services or healthchecks failed"

    log_info "Funkwhale server ready at https://localhost"
}

main(){
    log_info "Starting Funkwhale server + app setup"
    setup_server
    adb_install_apk "$APK_PATH"
    log_info "Setup complete"
}

main "$@"
