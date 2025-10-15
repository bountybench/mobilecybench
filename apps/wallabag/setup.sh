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

EMU="$ANDROID_HOME/emulator/emulator"
if [ ! -x "$EMU" ]; then
  echo "Error: Emulator binary not found at $EMU"
  exit 1
fi

# Start Docker backend services
echo "[Wallabag] Starting backend stack (Docker Compose)..."
# Stop any existing containers first
docker compose down 2>/dev/null || true
# Force rebuild to ensure we get the latest Dockerfile changes
docker compose build --no-cache wallabag
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
    
    if [ "$STATUS" == "healthy" ]; then
        sleep 15  # Wait for full startup
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

# Fetch login page to get CSRF token and save cookies
echo "Waiting 10s for Wallabag to finish internal initialization..."
sleep 10

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

# --- Android emulator setup and APK install ---

APK=apk/wallabag-release.apk
if [ ! -f "$APK" ]; then
    echo "Error: APK not found! Please build or download it first."
    exit 1
fi

echo "Available AVDs:"
$EMU -list-avds

AVD_NAME=$($EMU -list-avds | head -n 1)
if [ -z "$AVD_NAME" ]; then
    echo "Error: No Android Virtual Device (AVD) found. Please create one."
    
    # In CI, try to create a basic AVD if none exists
    if [ -n "$GITHUB_ACTIONS" ] || [ -n "$CI" ]; then
        echo "[Wallabag] CI environment: Attempting to create a basic AVD..."
        echo "no" | avdmanager create avd -n "test_avd" -k "system-images;android-34;google_atd;x86_64" -f 2>/dev/null || true
        AVD_NAME="test_avd"
        if [ -z "$($EMU -list-avds | grep "$AVD_NAME")" ]; then
            echo "[Wallabag] Failed to create AVD, cannot proceed without emulator"
            exit 1
        fi
    else
        exit 1
    fi
fi
echo "Using AVD: $AVD_NAME"

# echo "[Wallabag] Starting emulator..."

# # Check if we're in CI and adjust emulator parameters
# if [ -n "$GITHUB_ACTIONS" ] || [ -n "$CI" ]; then
#     echo "[Wallabag] CI environment detected, using headless emulator settings"
#     $EMU -avd "$AVD_NAME" -no-snapshot-load -no-audio -no-window -no-boot-anim -verbose -netdelay none -netspeed full -gpu swiftshader_indirect -no-metrics -memory 2048 -cores 2 -read-only &
#     EMULATOR_PID=$!
#     sleep 30
    
#     # Check if emulator process is still alive
#     if ! kill -0 $EMULATOR_PID 2>/dev/null; then
#         echo "[Wallabag] Warning: Emulator process died, trying alternative configuration..."
#         $EMU -avd "$AVD_NAME" -no-snapshot-load -no-audio -no-window -no-boot-anim -verbose -netdelay none -netspeed full -gpu off -no-metrics -read-only &
#         EMULATOR_PID=$!
#         sleep 15
#     fi
# else
#     $EMU -avd "$AVD_NAME" -no-snapshot-load -no-audio -no-window -verbose -netdelay none -netspeed full -read-only &
#     EMULATOR_PID=$!
# fi

# echo "Waiting for emulator in adb devices (timeout 180s)..."
# TIMEOUT=180
# START_TIME=$(date +%s)
# while true; do
#     EMULATOR_STATE=$(adb devices | grep emulator | grep device || true)
#     if [ -n "$EMULATOR_STATE" ]; then
#         echo "Emulator detected and ready."
#         break
#     fi
    
#     CURRENT_TIME=$(date +%s)
#     ELAPSED=$((CURRENT_TIME - START_TIME))
#     if [ "$ELAPSED" -ge "$TIMEOUT" ]; then
#         echo "Timeout waiting for emulator."
#         exit 1
#     fi
#     sleep 5
# done


echo "[Wallabag] Debug: Testing network connectivity..."
if nc -zv localhost 8080 2>&1 | grep -q succeeded; then
  echo "Wallabag reachable on host: localhost:8080"
elif nc -zv 10.0.2.2 8080 2>&1 | grep -q succeeded; then
  echo "Wallabag reachable from emulator: 10.0.2.2:8080"
else
  echo "ERROR: Cannot reach app server!"
  exit 1
fi

echo "Emulator connected, waiting 60 more seconds for boot completion..."
sleep 60

adb install -r "$APK"

echo "[Wallabag] APK installed successfully."
echo "[Wallabag] Setup script complete."
echo "Exported WALLABAG_OAUTH_TOKEN for agent use."
