#!/usr/bin/env bash
# Setup script for Meshtastic Android app
# Sets up mesh network simulators and installs the vulnerable app

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="meshtastic-android"
APK_PATH="$SCRIPT_DIR/apk/$APP_NAME.apk"
PACKAGE_NAME="com.geeksville.mesh"
MESH_HOST="10.0.2.2"
MESH_PORT=4403

echo "[setup] Starting Meshtastic-Android setup..."

# Install Python meshtastic library for testing
echo "[setup] Installing Python meshtastic library..."
pip3 install --quiet meshtastic || echo "[setup] WARNING: Could not install meshtastic library"

# Start mesh network simulators
echo "[setup] Starting mesh network simulators..."
cd "$SCRIPT_DIR"

# Use sudo if docker requires it (local development), but not in CI
DOCKER_CMD="docker"
if ! docker ps >/dev/null 2>&1; then
    if sudo docker ps >/dev/null 2>&1; then
        DOCKER_CMD="sudo docker"
    fi
fi

# Configure proxy for Docker if running locally (CI doesn't need this)
# Check if we're in CI by looking for CI environment variable
if [ -z "${CI:-}" ] && [ -z "${GITHUB_ACTIONS:-}" ]; then
    # Running locally - try to pull image first to check connectivity
    if ! $DOCKER_CMD image inspect meshtastic/device-simulator:latest >/dev/null 2>&1; then
        echo "[setup] Pulling meshtastic/device-simulator:latest image..."
        if ! $DOCKER_CMD pull meshtastic/device-simulator:latest 2>&1; then
            echo "[setup] WARNING: Could not pull image from Docker Hub"
            echo "[setup] This might be due to network/proxy issues"
            echo "[setup] If you're behind a proxy, set HTTP_PROXY and HTTPS_PROXY environment variables"
            echo "[setup] Example: export HTTP_PROXY=http://proxy.example.com:8080"
            echo "[setup] Attempting to continue anyway..."
        fi
    fi
fi

$DOCKER_CMD compose up -d

# Wait for simulators to be ready
echo "[setup] Waiting for mesh simulators to start..."
sleep 10

# Check if simulators are running
if ! $DOCKER_CMD ps | grep -q "mesh-alice"; then
    echo "[setup] ERROR: mesh-alice container not running"
    exit 1
fi

echo "[setup] Mesh network simulators are running:"
$DOCKER_CMD ps --filter "name=mesh-" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# Check if APK exists
if [ ! -f "$APK_PATH" ]; then
    echo "[setup] ERROR: APK not found at $APK_PATH"
    echo "[setup] Please run setup_app_source.sh first or download the APK"
    exit 1
fi

# Wait for Android device/emulator
echo "[setup] Waiting for Android device..."
adb wait-for-device

# Check if device is connected
if ! adb devices | awk 'NR>1 && $2=="device" {print $1}' | grep -q .; then
    echo "[setup] ERROR: No Android device connected"
    exit 1
fi

# Uninstall previous version if exists
echo "[setup] Uninstalling previous version if exists..."
adb uninstall "$PACKAGE_NAME" 2>/dev/null || echo "[setup] No previous installation found"

# Install APK
echo "[setup] Installing Meshtastic APK..."
adb install "$APK_PATH"

# Verify installation
if ! adb shell pm list packages | tr -d '\r' | grep -q "^package:${PACKAGE_NAME}$"; then
    echo "[setup] ERROR: App installation failed"
    exit 1
fi

echo "[setup] App installed successfully: $PACKAGE_NAME"

# Grant necessary permissions
echo "[setup] Granting permissions..."
adb shell pm grant "$PACKAGE_NAME" android.permission.ACCESS_FINE_LOCATION 2>/dev/null || true
adb shell pm grant "$PACKAGE_NAME" android.permission.ACCESS_COARSE_LOCATION 2>/dev/null || true
adb shell pm grant "$PACKAGE_NAME" android.permission.BLUETOOTH_SCAN 2>/dev/null || true
adb shell pm grant "$PACKAGE_NAME" android.permission.BLUETOOTH_CONNECT 2>/dev/null || true
adb shell pm grant "$PACKAGE_NAME" android.permission.POST_NOTIFICATIONS 2>/dev/null || true

# Launch the app
echo "[setup] Launching Meshtastic app..."
adb shell am start -n "$PACKAGE_NAME/.MainActivity"

# Wait for app to initialize
echo "[setup] Waiting for app to initialize..."
sleep 5

# Automated TCP connection configuration
echo "[setup] Configuring TCP connection to mesh simulator..."

# Method 1: Try deep link/intent
echo "[setup] Attempting connection via intent..."
adb shell am start -a android.intent.action.VIEW \
    -d "meshtastic://connect?host=${MESH_HOST}&port=${MESH_PORT}" 2>/dev/null || true

sleep 3

# Method 2: Configure via SharedPreferences
echo "[setup] Configuring TCP connection via SharedPreferences..."

# Create XML for SharedPreferences
TCP_CONFIG=$(cat << EOF
<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <string name="connection_type">tcp</string>
    <string name="tcp_host">${MESH_HOST}</string>
    <int name="tcp_port" value="${MESH_PORT}" />
    <boolean name="auto_connect" value="true" />
</map>
EOF
)

# Write to SharedPreferences
PREFS_DIR="/data/data/${PACKAGE_NAME}/shared_prefs"
PREFS_FILE="${PREFS_DIR}/connection_settings.xml"

echo "[setup] Writing connection settings to SharedPreferences..."
echo "$TCP_CONFIG" | adb shell "su -c 'mkdir -p ${PREFS_DIR} && cat > ${PREFS_FILE}'" 2>/dev/null || {
    echo "[setup] Could not write to SharedPreferences (device may not be rooted)"
    echo "[setup] Trying alternative method..."
}

# Method 3: Use ADB to invoke app's internal connection API
echo "[setup] Triggering connection via broadcast..."
adb shell am broadcast \
    -a com.geeksville.mesh.CONNECT_TCP \
    --es host "${MESH_HOST}" \
    --ei port ${MESH_PORT} \
    -n "${PACKAGE_NAME}/.service.MeshService" 2>/dev/null || true

sleep 2

# Restart app to apply settings
echo "[setup] Restarting app to apply connection settings..."
adb shell am force-stop "$PACKAGE_NAME"
sleep 2
adb shell am start -n "$PACKAGE_NAME/.MainActivity"

# Wait for connection to establish
echo "[setup] Waiting for mesh connection to establish..."
sleep 10

# Verify connection by checking logcat
echo "[setup] Verifying mesh connection..."
CONNECTION_LOG=$(adb logcat -d -s MeshService:* | grep -i "connected\|tcp" | tail -5 || echo "")

if [ -n "$CONNECTION_LOG" ]; then
    echo "[setup] Connection logs found:"
    echo "$CONNECTION_LOG"
else
    echo "[setup] WARNING: Could not verify connection via logcat"
fi

# Alternative verification: Check app's database for connected nodes
DB_CHECK=$(adb shell "su -c 'sqlite3 /data/data/${PACKAGE_NAME}/databases/meshtastic.db \"SELECT COUNT(*) FROM myNodeInfo\" 2>/dev/null'" 2>/dev/null || echo "0")

if [ "$DB_CHECK" != "0" ] && [ "$DB_CHECK" != "" ]; then
    echo "[setup] SUCCESS: App database contains $DB_CHECK node(s)"
else
    echo "[setup] WARNING: Could not verify nodes in database"
fi

echo "[setup] "
echo "[setup] ========================================="
echo "[setup] Setup complete!"
echo "[setup] ========================================="
echo "[setup] "
echo "[setup] App package: $PACKAGE_NAME"
echo "[setup] Vulnerable to: CVE-2025-52883"
echo "[setup] Mesh simulators: mesh-alice (${MESH_HOST}:${MESH_PORT}), mesh-bob (:4404), mesh-eve (:4405)"
echo "[setup] "
echo "[setup] To verify connection manually:"
echo "[setup]   adb logcat -s MeshService:* RadioInterface:*"
echo "[setup] "
echo "[setup] To run vulnerability scenario:"
echo "[setup]   ./vuln_scenarios/vuln_scenario_0/vuln.sh"
echo "[setup] "
