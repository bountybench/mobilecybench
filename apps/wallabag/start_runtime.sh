#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "wallabag" "$@")
cd "$SCRIPT_DIR"

echo "[Wallabag] Setup begin..."

docker compose down 2>/dev/null || true
docker compose up --build -d

# Wait for Wallabag container to be healthy
echo "[Wallabag] Waiting for services to be ready..."
WAITED=0
while [ "$WAITED" -lt 120 ]; do
    STATUS=$(docker inspect --format='{{.State.Health.Status}}' wallabag 2>/dev/null || echo "unknown")
    [[ "$STATUS" == "healthy" ]] && break
    [[ "$WAITED" -ge 120 ]] && { echo "[Wallabag] ERROR: Not healthy after 120s"; exit 1; }
    sleep 3
    WAITED=$((WAITED + 3))
done

# Wait for web interface
echo "[Wallabag] Waiting for web interface..."
for i in $(seq 1 20); do
    curl -s --connect-timeout 5 http://localhost:8080/login >/dev/null 2>&1 && break
    [[ $i -eq 20 ]] && { echo "[Wallabag] ERROR: Web interface not ready"; exit 1; }
    sleep 3
done

curl -c cookies.txt -s -L http://localhost:8080/login -o login.html
if [ ! -f login.html ] || [ ! -s login.html ]; then
    echo "[Wallabag] ERROR: Failed to fetch login page or page is empty"
    exit 1
fi

CSRF_TOKEN=$(grep 'name="_csrf_token"' login.html | head -1 | sed 's/.*value="\([^"]*\)".*/\1/')
if [ -z "$CSRF_TOKEN" ]; then
    echo "[Wallabag] ERROR: Could not extract CSRF token from login page"
    exit 1
fi
echo "CSRF token for login: $CSRF_TOKEN"

# Submit login form with username, password and extracted CSRF token
curl -b cookies.txt -c cookies.txt -s -L -d "_username=wallabag&_password=wallabag&_csrf_token=$CSRF_TOKEN&_remember_me=on" \
  http://localhost:8080/login_check -o home.html

if [ ! -f home.html ] || [ ! -s home.html ]; then
    echo "[Wallabag] ERROR: Login failed - home page is empty or missing"
    exit 1
fi

# Check if login was successful
if grep -q "login" home.html && ! grep -q "dashboard\|entries\|unread" home.html; then
    echo "[Wallabag] ERROR: Login appears to have failed - still on login page"
    exit 1
fi

# Fetch OAuth client creation page to get new CSRF token
curl -b cookies.txt -c cookies.txt -s -L http://localhost:8080/developer/client/create -o client_form.html
if [ ! -f client_form.html ] || [ ! -s client_form.html ]; then
    echo "[Wallabag] ERROR: Failed to fetch client creation page"
    exit 1
fi

CLIENT_CSRF_TOKEN=$(grep 'name="client\[_token\]"' client_form.html | head -1 | sed 's/.*value="\([^"]*\)".*/\1/')
if [ -z "$CLIENT_CSRF_TOKEN" ]; then
    echo "[Wallabag] ERROR: Could not extract client CSRF token"
    exit 1
fi
echo "CSRF token for client creation: $CLIENT_CSRF_TOKEN"

# Create new OAuth client with name, redirect URI, CSRF token, and submit action
curl -b cookies.txt -c cookies.txt -s -L -d "client[name]=mobilecybench&client[redirect_uris]=http://localhost:8080&client[_token]=$CLIENT_CSRF_TOKEN&client[save]=Create a new client" \
  http://localhost:8080/developer/client/create -o client_created.html

if [ ! -f client_created.html ] || [ ! -s client_created.html ]; then
    echo "[Wallabag] ERROR: Failed to create OAuth client"
    exit 1
fi

# Extract Client ID and Client Secret from response HTML
CLIENT_ID=$(sed -n '/Client ID/{n;n;s/.*<code>\([^<]*\)<\/code>.*/\1/p;}' client_created.html)
CLIENT_SECRET=$(sed -n '/Client secret/{n;n;s/.*<code>\([^<]*\)<\/code>.*/\1/p;}' client_created.html)

if [ -z "$CLIENT_ID" ] || [ -z "$CLIENT_SECRET" ]; then
    echo "[Wallabag] ERROR: Could not extract Client ID or Secret"
    exit 1
fi

echo "[Wallabag] Obtaining OAuth2 token..."
TOKEN_RESPONSE=$(curl -s -X POST http://localhost:8080/oauth/v2/token \
  -d grant_type=password \
  -d client_id="$CLIENT_ID" \
  -d client_secret="$CLIENT_SECRET" \
  -d username=wallabag \
  -d password=wallabag)

OAUTH_TOKEN=$(echo "$TOKEN_RESPONSE" | jq -r '.access_token' 2>/dev/null || echo "")

if [ "$OAUTH_TOKEN" == "null" ] || [ -z "$OAUTH_TOKEN" ]; then
  echo "Failed to obtain OAuth token"
  exit 1
fi
echo "[Wallabag] OAuth2 token obtained."
export WALLABAG_OAUTH_TOKEN=$OAUTH_TOKEN

# --- Android APK installation ---

adb_install_apk "$APK_PATH"

echo "[Wallabag] APK installed successfully."
echo "[Wallabag] Setup script complete."
echo "Exported WALLABAG_OAUTH_TOKEN for agent use."

