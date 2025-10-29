#!/bin/bash
set -e

echo "[Wallabag] MobileCybench setup begin..."

# Check required dependencies
DEPENDENCIES=(adb docker curl)
for dep in "${DEPENDENCIES[@]}"; do
    if ! command -v $dep >/dev/null 2>&1; then
        echo "Error: $dep is required but not installed."
        exit 1
    fi
done

# Set Android SDK environment variables (adjust if needed)
ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
export ANDROID_HOME
export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"

# Check if we're in GitHub Actions or CI environment
if [ -n "$GITHUB_ACTIONS" ] || [ -n "$CI" ]; then
    ANDROID_HOME="${ANDROID_HOME:-/usr/local/lib/android/sdk}"
    export ANDROID_HOME
    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"
fi

# Start Docker backend services
echo "[Wallabag] Starting backend stack (Docker Compose)..."
# Stop any existing containers first
docker compose down 2>/dev/null || true

# Start all services with rebuild
docker compose up --build -d

# Wait until Postgres is ready inside the container
echo "[Wallabag] Waiting for database to be ready..."
DB_MAX_WAIT=60
DB_WAITED=0
while true; do
    if docker exec wallabag-db-1 pg_isready -U wallabag >/dev/null 2>&1; then
        break
    fi
    
    if [ "$DB_WAITED" -ge "$DB_MAX_WAIT" ]; then
        echo "[Wallabag] ERROR: Database not ready after $DB_MAX_WAIT seconds"
        docker logs wallabag-db-1 --tail 20
        exit 1
    fi
    
    sleep 3
    DB_WAITED=$((DB_WAITED + 3))
done

# Wait until Wallabag container reports healthy status
echo "[Wallabag] Waiting for Wallabag container to be healthy..."
MAX_WAIT=60
WAITED=0
while true; do
    STATUS=$(docker inspect --format='{{.State.Health.Status}}' wallabag 2>/dev/null || echo "unknown")
    
    if [ "$STATUS" == "healthy" ]; then
        break
    fi
    
    if [ "$WAITED" -ge "$MAX_WAIT" ]; then
      echo "Wallabag container not healthy after $MAX_WAIT seconds."
      docker logs wallabag --tail 50
      exit 1
    fi
    sleep 3
    WAITED=$((WAITED + 3))
done

# --- Web login and client creation ---

# Wait for Wallabag web interface to be ready
echo "[Wallabag] Waiting for web interface to be ready..."
WEB_MAX_WAIT=60
WEB_WAITED=0
while true; do
    if curl -s --connect-timeout 5 --max-time 10 http://localhost:8080/login > /dev/null 2>&1; then
        echo "[Wallabag] Web interface is ready"
        break
    fi
    
    WEB_WAITED=$((WEB_WAITED + 5))
    if [ "$WEB_WAITED" -ge "$WEB_MAX_WAIT" ]; then
        echo "[Wallabag] ERROR: Web interface not ready after $WEB_MAX_WAIT seconds"
        docker logs wallabag --tail 20
        exit 1
    fi
    
    echo "[Wallabag] Web interface not ready, waiting..."
    sleep 2
    WEB_WAITED=$((WEB_WAITED + 2))
done

# Test connection with detailed error reporting
CURL_OUTPUT=$(curl -s --connect-timeout 10 --max-time 30 -w "HTTP_CODE:%{http_code}" http://localhost:8080/login 2>&1)
CURL_EXIT=$?

if [ $CURL_EXIT -ne 0 ]; then
    # Extract HTTP status from the curl output if possible
    HTTP_STATUS=$(echo "$CURL_OUTPUT" | grep -o "HTTP_CODE:[0-9]*" | cut -d: -f2 2>/dev/null || echo "unknown")
    
    # If we got a 200 status, the connection actually worked
    if [ "$HTTP_STATUS" = "200" ]; then
        echo "[Wallabag] Connection successful"
    else
        echo "[Wallabag] ERROR: Cannot connect to Wallabag at http://localhost:8080/login"
        docker logs wallabag --tail 20
        exit 1
    fi
fi

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

echo "New OAuth Client ID: $CLIENT_ID"
echo "New OAuth Client Secret: $CLIENT_SECRET"

# Obtain OAuth2 access token using the created client credentials
echo "[Wallabag] Obtaining OAuth2 token for agent..."
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

APK=apk/wallabag-release.apk
if [ ! -f "$APK" ]; then
    echo "Error: APK not found! Please build or download it first."
    exit 1
fi

adb install -r "$APK"

echo "[Wallabag] APK installed successfully."
echo "[Wallabag] Setup script complete."
echo "Exported WALLABAG_OAUTH_TOKEN for agent use."

