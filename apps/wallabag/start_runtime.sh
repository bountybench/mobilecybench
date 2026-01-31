#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "wallabag" "$@")
cd "$SCRIPT_DIR"

log_info "Setup begin..."

docker compose down 2>/dev/null || true
docker compose up --build -d

log_info "Waiting for services to be ready..."
WAITED=0
while [ "$WAITED" -lt 120 ]; do
    STATUS=$(docker inspect --format='{{.State.Health.Status}}' wallabag 2>/dev/null || echo "unknown")
    [[ "$STATUS" == "healthy" ]] && break
    [[ "$WAITED" -ge 120 ]] && fatal "Not healthy after 120s"
    sleep 3
    WAITED=$((WAITED + 3))
done

log_info "Waiting for web interface..."
for i in $(seq 1 20); do
    curl -s --connect-timeout 5 http://localhost:8080/login >/dev/null 2>&1 && break
    [[ $i -eq 20 ]] && fatal "Web interface not ready"
    sleep 3
done

curl -c cookies.txt -s -L http://localhost:8080/login -o login.html
if [ ! -f login.html ] || [ ! -s login.html ]; then
    fatal "Failed to fetch login page or page is empty"
fi

CSRF_TOKEN=$(grep 'name="_csrf_token"' login.html | head -1 | sed 's/.*value="\([^"]*\)".*/\1/')
if [ -z "$CSRF_TOKEN" ]; then
    fatal "Could not extract CSRF token from login page"
fi
log_info "CSRF token for login: $CSRF_TOKEN"

curl -b cookies.txt -c cookies.txt -s -L -d "_username=wallabag&_password=wallabag&_csrf_token=$CSRF_TOKEN&_remember_me=on" \
  http://localhost:8080/login_check -o home.html

if [ ! -f home.html ] || [ ! -s home.html ]; then
    fatal "Login failed - home page is empty or missing"
fi

if grep -q "login" home.html && ! grep -q "dashboard\|entries\|unread" home.html; then
    fatal "Login appears to have failed - still on login page"
fi

curl -b cookies.txt -c cookies.txt -s -L http://localhost:8080/developer/client/create -o client_form.html
if [ ! -f client_form.html ] || [ ! -s client_form.html ]; then
    fatal "Failed to fetch client creation page"
fi

CLIENT_CSRF_TOKEN=$(grep 'name="client\[_token\]"' client_form.html | head -1 | sed 's/.*value="\([^"]*\)".*/\1/')
if [ -z "$CLIENT_CSRF_TOKEN" ]; then
    fatal "Could not extract client CSRF token"
fi
log_info "CSRF token for client creation: $CLIENT_CSRF_TOKEN"

curl -b cookies.txt -c cookies.txt -s -L -d "client[name]=mobilecybench&client[redirect_uris]=http://localhost:8080&client[_token]=$CLIENT_CSRF_TOKEN&client[save]=Create a new client" \
  http://localhost:8080/developer/client/create -o client_created.html

if [ ! -f client_created.html ] || [ ! -s client_created.html ]; then
    fatal "Failed to create OAuth client"
fi

CLIENT_ID=$(sed -n '/Client ID/{n;n;s/.*<code>\([^<]*\)<\/code>.*/\1/p;}' client_created.html)
CLIENT_SECRET=$(sed -n '/Client secret/{n;n;s/.*<code>\([^<]*\)<\/code>.*/\1/p;}' client_created.html)

if [ -z "$CLIENT_ID" ] || [ -z "$CLIENT_SECRET" ]; then
    fatal "Could not extract Client ID or Secret"
fi

log_info "Obtaining OAuth2 token..."
TOKEN_RESPONSE=$(curl -s -X POST http://localhost:8080/oauth/v2/token \
  -d grant_type=password \
  -d client_id="$CLIENT_ID" \
  -d client_secret="$CLIENT_SECRET" \
  -d username=wallabag \
  -d password=wallabag)

OAUTH_TOKEN=$(echo "$TOKEN_RESPONSE" | jq -r '.access_token' 2>/dev/null || echo "")

if [ "$OAUTH_TOKEN" == "null" ] || [ -z "$OAUTH_TOKEN" ]; then
  fatal "Failed to obtain OAuth token"
fi
log_info "OAuth2 token obtained."
export WALLABAG_OAUTH_TOKEN=$OAUTH_TOKEN

adb_install_apk "$APK_PATH"

log_info "APK installed successfully."
log_info "Setup script complete."
log_info "Exported WALLABAG_OAUTH_TOKEN for agent use."
