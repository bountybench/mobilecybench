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

setup_ssl_certificates(){
    local server_dir="$1"

    info "Setting up SSL certificates for HTTPS testing"

    # Create SSL directory
    mkdir -p "$server_dir/ssl"

    # Check if certificates already exist
    if [[ -f "$server_dir/ssl/server.crt" ]] && [[ -f "$server_dir/ssl/server.key" ]]; then
        info "SSL certificates already exist"
        return 0
    fi

    # Check if openssl is available
    if ! command_exists openssl; then
        warn "openssl not found, skipping HTTPS setup"
        return 1
    fi

    info "Generating self-signed SSL certificates..."
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout "$server_dir/ssl/server.key" \
        -out "$server_dir/ssl/server.crt" \
        -subj "/C=US/ST=State/L=City/O=MobileCybench/CN=funkwhale.local" \
        2>/dev/null || {
            warn "Failed to generate SSL certificates, skipping HTTPS setup"
            return 1
        }

    # Generate DER format certificate for Android
    openssl x509 -outform der \
        -in "$server_dir/ssl/server.crt" \
        -out "$server_dir/ssl/server.der.crt" \
        2>/dev/null || warn "Failed to generate DER certificate"

    info "✓ SSL certificates generated"
    return 0
}

create_nginx_config(){
    local server_dir="$1"

    # Check if nginx.conf already exists
    if [[ -f "$server_dir/nginx.conf" ]]; then
        info "nginx.conf already exists"
        return 0
    fi

    info "Creating nginx configuration with HTTP..."
    cat > "$server_dir/nginx.conf" << 'NGINX_EOF'
upstream funkwhale-api {
    server api:5000;
}

map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 80;
    listen [::]:80;
    server_name _;

    # General configs
    root /usr/share/nginx/html;
    client_max_body_size 100M;
    charset utf-8;

    # Compression settings
    gzip on;
    gzip_comp_level 5;
    gzip_min_length 256;
    gzip_proxied any;
    gzip_vary on;
    gzip_types
        application/javascript
        application/json
        application/vnd.geo+json
        application/vnd.ms-fontobject
        application/x-font-ttf
        application/x-web-app-manifest+json
        font/opentype
        image/bmp
        image/svg+xml
        image/x-icon
        text/cache-manifest
        text/css
        text/plain
        text/vcard
        text/vnd.rim.location.xloc
        text/vtt
        text/x-component
        text/x-cross-domain-policy;

    # API proxy
    location /api/ {
        proxy_pass http://funkwhale-api;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host:$server_port;
        proxy_redirect off;
    }

    # Static files and frontend
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Media files
    location /media/ {
        alias /srv/funkwhale/data/media/;
    }

    # Static files
    location /staticfiles/ {
        alias /usr/share/nginx/html/staticfiles/;
    }

    # Well-known endpoints
    location /.well-known/ {
        proxy_pass http://funkwhale-api;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
NGINX_EOF

    info "✓ nginx.conf created"
    return 0
}

patch_docker_compose_for_https(){
    local server_dir="$1"
    local compose_file="$server_dir/docker-compose.yml"

    info "Checking docker-compose.yml for HTTPS configuration..."

    # Check if already patched
    if grep -q 'nginx.conf:/etc/nginx/templates/default.conf.template' "$compose_file" 2>/dev/null; then
        info "docker-compose.yml already configured for HTTPS"
        return 0
    fi

    # Create backup if it doesn't exist
    if [[ ! -f "${compose_file}.orig" ]]; then
        cp "$compose_file" "${compose_file}.orig"
        info "Created backup: docker-compose.yml.orig"
    fi

    info "Patching docker-compose.yml for HTTPS support..."

    # Find the line with STATIC_ROOT volume mount and add nginx config mounts after it
    if grep -q "STATIC_ROOT.*staticfiles:ro" "$compose_file"; then
        # Add nginx.conf and ssl mounts after the STATIC_ROOT line
        sed -i.tmp '/STATIC_ROOT.*staticfiles:ro/a\
      - "./nginx.conf:/etc/nginx/templates/default.conf.template"\
      - "./ssl:/etc/nginx/ssl:ro"
' "$compose_file"
    fi

    # Update ports to include 443 if not already present
    if ! grep -q "443:443" "$compose_file"; then
        # Add 443 port after 80:80 in the front service
        sed -i.tmp '/front:/,/^  [a-z]/ {
            /- "80:80"/a\
      - "443:443"
        }' "$compose_file"
    fi

    # Clean up temp file
    rm -f "${compose_file}.tmp"

    info "✓ docker-compose.yml patched for HTTPS"
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

    # Verify installation
    verify_installation

    # Launch the app
    launch_app

    info "Funkwhale server + app setup completed successfully!"
   }

main "$@"
