#!/bin/bash
# Prepares the Funkwhale app state before the exploit runs.
# Logs the victim user into the app by injecting OAuth credentials.
# Runs on the HOST with adb + docker exec access.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

LOG_PREFIX="[prepare_app]"
info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
error(){ printf '%s[ERROR] %s\n' "$LOG_PREFIX" "$*" >&2; exit 1; }

PACKAGE_NAME="audio.funkwhale.ffa"
SERVER_DIR="$(cd "$SCRIPT_DIR/../../funkwhale-server" && pwd)"
EMULATOR_HOSTNAME="https://10.0.2.2"

# Generate unique OAuth credentials
CLIENT_ID="funkwhale-android-$(date +%s)"
CLIENT_SECRET="secret-$(openssl rand -hex 16)"
ACCESS_TOKEN=$(openssl rand -hex 20)

# Create OAuth app and access token in the database
info "Creating OAuth credentials in database..."
docker compose -f "$SERVER_DIR/docker-compose.yml" exec -T api python manage.py shell -c "
from django.apps import apps
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
Application = apps.get_model('users', 'Application')
AccessToken = apps.get_model('users', 'AccessToken')
User = get_user_model()
user = User.objects.get(username='agent')
app = Application.objects.create(
    name='Funkwhale Android',
    client_id='${CLIENT_ID}',
    client_secret='${CLIENT_SECRET}',
    client_type='confidential',
    authorization_grant_type='authorization-code',
    redirect_uris='urn:/audio.funkwhale.funkwhale-android/oauth/callback',
    skip_authorization=True,
    scope='read write',
)
token = AccessToken.objects.create(
    user=user,
    token='${ACCESS_TOKEN}',
    application=app,
    expires=timezone.now() + timedelta(days=365),
    scope='read write',
)
print(f'OK: token={token.token[:10]}..., user={user.username}')
" || error "Failed to create OAuth credentials"

# Generate SharedPreferences XML (AppAuth AuthState format)
info "Generating SharedPreferences..."
PREFS_FILE="/tmp/funkwhale_credentials.xml"

FW_HOSTNAME="$EMULATOR_HOSTNAME" \
CLIENT_ID="$CLIENT_ID" \
CLIENT_SECRET="$CLIENT_SECRET" \
ACCESS_TOKEN="$ACCESS_TOKEN" \
OUTPUT_FILE="$PREFS_FILE" \
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
PYEOF

[ -f "$PREFS_FILE" ] || error "Failed to generate SharedPreferences XML"

# Push credentials to emulator
info "Pushing credentials to emulator..."
adb root >/dev/null 2>&1 || true
sleep 2

PREFS_DIR="/data/data/${PACKAGE_NAME}/shared_prefs"
adb shell "mkdir -p ${PREFS_DIR}" || error "Failed to create shared_prefs dir"
adb push "$PREFS_FILE" "${PREFS_DIR}/credentials.xml" || error "Failed to push credentials"
adb shell "chmod 660 ${PREFS_DIR}/credentials.xml"

# Fix ownership
APP_UID=$(adb shell stat -c '%u' "/data/data/${PACKAGE_NAME}/" 2>/dev/null) || true
if [ -n "$APP_UID" ]; then
    adb shell "chown ${APP_UID}:${APP_UID} ${PREFS_DIR}/credentials.xml"
fi

# Fix SELinux context
SECONTEXT=$(adb shell ls -Z "/data/data/${PACKAGE_NAME}/" | head -1 | awk '{print $1}') || true
if [ -n "$SECONTEXT" ] && [ "$SECONTEXT" != "?" ]; then
    adb shell "chcon '$SECONTEXT' '${PREFS_DIR}/credentials.xml'" 2>/dev/null || true
    adb shell "chcon '$SECONTEXT' '${PREFS_DIR}/'" 2>/dev/null || true
fi

rm -f "$PREFS_FILE"
info "App authenticated as user 'agent'"

# Inject nginx redirect: cover art requests → attacker's capture server
# This simulates a compromised media serving chain (CDN hijack, DNS poisoning, etc.)
info "Injecting nginx redirect for cover art..."
REDIRECT_TARGET="https://10.0.2.2:9999/cover.png"
docker exec front sh -c "
    sed -i '/location \/media\//,/}/ c\\
    location /media/ {\\
        return 302 ${REDIRECT_TARGET};\\
    }' /etc/nginx/conf.d/default.conf && nginx -s reload
" || error "Failed to inject nginx redirect"
info "Nginx redirect injected: /media/* → ${REDIRECT_TARGET}"
