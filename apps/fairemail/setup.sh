#!/bin/bash
set -e

FAIREMAIL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MOBILECYBENCH_ROOT="$(cd "$FAIREMAIL_DIR/../.." && pwd)"

echo "=== FairEmail setup ==="

# Ensure shared_net network exists
if ! docker network ls | grep -q "shared_net"; then
    echo "Creating shared_net Docker network..."
    docker network create shared_net || echo "shared_net network may already exist"
fi

# Start the GreenMail mail server
echo "Starting GreenMail mail server..."
docker compose -f "$FAIREMAIL_DIR/docker-compose.yml" up -d

# Wait for GreenMail to be ready by checking port availability
echo "Waiting for GreenMail mail server to start..."
TIMEOUT=60
INTERVAL=2
elapsed=0

while [ $elapsed -lt $TIMEOUT ]; do
    # Check if SMTP port (1025) is available on host
    if nc -z localhost 1025 2>/dev/null; then
        # Also check IMAP port (1143)
        if nc -z localhost 1143 2>/dev/null; then
            echo "GreenMail mail server is ready (SMTP: 1025, IMAP: 1143)"
            break
        fi
    fi
    
    if [ $elapsed -ge $TIMEOUT ]; then
        echo "[WARNING] GreenMail not ready after ${TIMEOUT}s. Proceeding anyways."
        break
    fi
    
    sleep $INTERVAL
    elapsed=$((elapsed + INTERVAL))
done

# Verify the container is running
if docker ps | grep -q "fairemail-mailserver"; then
    echo "GreenMail container is running"
else
    echo "[WARNING] GreenMail container may not be running properly"
    docker ps -a | grep fairemail-mailserver || true
fi

# Check for APK
APK_DIR="$FAIREMAIL_DIR/apk"
APK_FILE=""

if [ -d "$APK_DIR" ]; then
    APK_FILE=$(find "$APK_DIR" -maxdepth 1 -name "*.apk" -type f 2>/dev/null | head -1)
fi

if [ -z "$APK_FILE" ] || [ ! -f "$APK_FILE" ]; then
    echo "[ERROR] APK not found in $APK_DIR"
    echo "[ERROR] Run setup_app_source.sh first to build the APK"
    exit 1
fi

echo "Found APK: $APK_FILE"

# Get package name from metadata
METADATA_FILE="$FAIREMAIL_DIR/metadata.json"
PACKAGE_NAME=$(jq -r '.package_name' "$METADATA_FILE" 2>/dev/null)
if [ -z "$PACKAGE_NAME" ] || [ "$PACKAGE_NAME" = "null" ]; then
    echo "[ERROR] package_name not found in metadata.json"
    exit 1
fi

# Check for Android emulator
if ! adb devices | grep -q "device$"; then
    echo "[ERROR] No Android emulator detected"
    echo "Please start an emulator and try again"
    exit 1
fi

echo "Installing APK for package: $PACKAGE_NAME"
if ! adb install -r "$APK_FILE"; then
    echo "[ERROR] Failed to install APK"
    exit 1
fi

sleep 2

# Verify installation
if ! adb shell pm list packages | grep -q "package:$PACKAGE_NAME"; then
    echo "[ERROR] Package $PACKAGE_NAME is not installed after setup.sh"
    echo "This indicates the APK installation failed silently"
    exit 1
fi

echo "Successfully verified package $PACKAGE_NAME is installed"

# Launch the app
echo "Launching FairEmail..."
adb shell am start -n eu.faircode.email/.ActivityMain || true

echo ""
echo "=== FairEmail setup complete ==="
echo ""
echo "Mail server configuration for FairEmail:"
echo "  IMAP Host: 10.0.2.2"
echo "  IMAP Port: 1143"
echo "  SMTP Host: 10.0.2.2"
echo "  SMTP Port: 1025"
echo "  Username: user@fairemail.test"
echo "  Password: password123"
echo ""
echo "For container-to-container access (agent/runner):"
echo "  IMAP: fairemail-mailserver:3143"
echo "  SMTP: fairemail-mailserver:3025"
