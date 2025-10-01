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

EMU="$ANDROID_HOME/emulator/emulator"
if [ ! -x "$EMU" ]; then
  echo "Error: Emulator binary not found at $EMU"
  exit 1
fi

# Start Docker backend services
echo "[Wallabag] Starting backend stack (Docker Compose)..."
docker compose up -d db redis wallabag

# Wait until Postgres is ready inside the container
echo "[Wallabag] Waiting for database to be ready..."
until docker exec wallabag-db-1 pg_isready -U wallabag >/dev/null 2>&1; do
    sleep 3
done

# Wait until Wallabag container reports healthy status
echo "[Wallabag] Waiting for Wallabag container to be healthy..."
MAX_WAIT=60
WAITED=0
while true; do
    STATUS=$(docker inspect --format='{{.State.Health.Status}}' wallabag 2>/dev/null || echo "unknown")
    [ "$STATUS" == "healthy" ] && break
    [ "$WAITED" -ge "$MAX_WAIT" ] && {
      echo "Wallabag container not healthy after $MAX_WAIT seconds."
      docker logs wallabag --tail 50
      exit 1
    }
    sleep 3
    WAITED=$((WAITED + 3))
done

# Run wallabag install command inside container
docker exec wallabag bin/console wallabag:install --env=prod -n || true

# Clear cache and fix permissions inside container
docker exec wallabag rm -rf /var/www/wallabag/var/cache/prod
docker exec wallabag php bin/console cache:clear --env=prod
docker exec wallabag chown -R nobody:nogroup /var/www/wallabag/var
docker exec wallabag chmod -R 770 /var/www/wallabag/var

# Restart Wallabag container to apply changes
docker compose restart wallabag

# Wait again for healthy status after restart
WAITED=0
while true; do
    STATUS=$(docker inspect --format='{{.State.Health.Status}}' wallabag 2>/dev/null || echo "unknown")
    [ "$STATUS" == "healthy" ] && break
    [ "$WAITED" -ge "$MAX_WAIT" ] && {
      echo "Wallabag container not healthy after restart $MAX_WAIT seconds."
      docker logs wallabag --tail 50
      exit 1
    }
    sleep 3
    WAITED=$((WAITED + 3))
done

# --- Web login and client creation ---

# Fetch login page to get CSRF token and save cookies
curl -c cookies.txt -s -L http://localhost:8080/login -o login.html
CSRF_TOKEN=$(grep 'name="_csrf_token"' login.html | head -1 | sed 's/.*value="\([^"]*\)".*/\1/')
echo "CSRF token for login: $CSRF_TOKEN"

# Submit login form with username, password and extracted CSRF token
curl -b cookies.txt -c cookies.txt -s -L -d "_username=wallabag&_password=wallabag&_csrf_token=$CSRF_TOKEN&_remember_me=on" \
  http://localhost:8080/login_check -o home.html

# Fetch OAuth client creation page to get new CSRF token
curl -b cookies.txt -c cookies.txt -s -L http://localhost:8080/developer/client/create -o client_form.html
CLIENT_CSRF_TOKEN=$(grep 'name="client\[_token\]"' client_form.html | head -1 | sed 's/.*value="\([^"]*\)".*/\1/')
echo "CSRF token for client creation: $CLIENT_CSRF_TOKEN"

# Create new OAuth client with name, redirect URI, CSRF token, and submit action
curl -b cookies.txt -c cookies.txt -s -L -d "client[name]=mobilecybench&client[redirect_uris]=http://localhost:8080&client[_token]=$CLIENT_CSRF_TOKEN&client[save]=Create a new client" \
  http://localhost:8080/developer/client/create -o client_created.html

# Extract Client ID and Client Secret from response HTML
CLIENT_ID=$(sed -n '/Client ID/{n;n;s/.*<code>\([^<]*\)<\/code>.*/\1/p;}' client_created.html)
CLIENT_SECRET=$(sed -n '/Client secret/{n;n;s/.*<code>\([^<]*\)<\/code>.*/\1/p;}' client_created.html)
echo "New OAuth Client ID: $CLIENT_ID"
echo "New OAuth Client Secret: $CLIENT_SECRET"

# Obtain OAuth2 access token using the created client credentials
echo "[Wallabag] Obtaining OAuth2 token for agent..."
OAUTH_TOKEN=$(curl -s -X POST http://localhost:8080/oauth/v2/token \
  -d grant_type=password \
  -d client_id="$CLIENT_ID" \
  -d client_secret="$CLIENT_SECRET" \
  -d username=wallabag \
  -d password=wallabag | jq -r '.access_token')

if [ "$OAUTH_TOKEN" == "null" ] || [ -z "$OAUTH_TOKEN" ]; then
  echo "Failed to obtain OAuth token"
  exit 1
fi
echo "[Wallabag] OAuth2 token obtained."
export WALLABAG_OAUTH_TOKEN=$OAUTH_TOKEN

# --- Android emulator setup and APK install ---

APK=wallabag-debug.apk
if [ ! -f "$APK" ]; then
    echo "Error: APK not found! Please build or download it first."
    exit 1
fi

echo "Available AVDs:"
$EMU -list-avds

AVD_NAME=$($EMU -list-avds | head -n 1)
if [ -z "$AVD_NAME" ]; then
    echo "Error: No Android Virtual Device (AVD) found. Please create one."
    exit 1
fi
echo "Using AVD: $AVD_NAME"

echo "[Wallabag] Starting emulator..."
$EMU -avd "$AVD_NAME" -no-snapshot-load -no-audio -no-window -verbose -netdelay none -netspeed full &

echo "Waiting for emulator in adb devices (timeout 180s)..."
TIMEOUT=180
START_TIME=$(date +%s)
while true; do
    EMULATOR_STATE=$(adb devices | grep emulator | grep device || true)
    if [ -n "$EMULATOR_STATE" ]; then
        echo "Emulator detected and ready."
        break
    fi
    CURRENT_TIME=$(date +%s)
    ELAPSED=$((CURRENT_TIME - START_TIME))
    if [ "$ELAPSED" -ge "$TIMEOUT" ]; then
        echo "Timeout waiting for emulator."
        exit 1
    fi
    sleep 5
done

if nc -zv wallabag 80 2>&1 | grep -q succeeded; then
  echo "Wallabag reachable via Docker network: wallabag:80"
elif nc -zv localhost 8080 2>&1 | grep -q succeeded; then
  echo "Wallabag reachable on host: localhost:8080"
elif nc -zv 10.0.2.2 8080 2>&1 | grep -q succeeded; then
  echo "Wallabag reachable from emulator: 10.0.2.2:8080"
else
  echo "ERROR: Cannot reach app server in any mode!"
  exit 1
fi

echo "Emulator connected, waiting 60 more seconds for boot completion..."
sleep 60

adb install -r "$APK"

echo "[Wallabag] APK installed successfully."
echo "[Wallabag] Setup script complete."
echo "Exported WALLABAG_OAUTH_TOKEN for agent use."
