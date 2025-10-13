#!/bin/bash
set -e

DELTACHAT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MOBILECYBENCH_ROOT="$(cd "$DELTACHAT_DIR/../.." && pwd)"

echo "=== RUNNING DeltaChat setup.sh ==="

echo "[INFO] Starting full email server (Postfix + Dovecot) for DeltaChat testing..."
docker compose -f "$DELTACHAT_DIR/docker-compose.yml" up --build -d
echo "[INFO] Email server started."

echo "[INFO] Waiting for email server to be ready..."
echo "[INFO] This may take 30-60 seconds for first startup..."
until nc -z localhost 1025 >/dev/null 2>&1 && nc -z localhost 1143 >/dev/null 2>&1; do
  sleep 5
done
echo "[INFO] Email server is up and ready (SMTP: 1025, IMAP: 1143)."

echo "[INFO] Creating test email accounts..."
cd "$MOBILECYBENCH_ROOT"
python3 "${DELTACHAT_DIR}/create_accounts.py"
if [ $? -eq 0 ]; then
  echo "[INFO] Email accounts created successfully."
else
  echo "[ERROR] Email account creation failed."
fi

echo "[INFO] Installing DeltaChat app..."

# Verify APK exists (should have been created by setup_app_source.sh or setup_app_apklink.sh)
APK_FILE="${DELTACHAT_DIR}/apk/deltachat-android.apk"
if [[ ! -f "$APK_FILE" ]]; then
    echo "[ERROR] APK not found at $APK_FILE"
    echo "[ERROR] Run setup_app_source.sh or setup_app_apklink.sh first to prepare the APK"
    exit 1
fi

echo "[INFO] APK found at $APK_FILE"

# Verify emulator is running
if ! adb devices | grep -q "device$"; then
    echo "[ERROR] No Android emulator detected. Please start the emulator first."
    exit 1
fi

# Install the APK
echo "[INFO] Installing DeltaChat APK..."
if adb install -r "$APK_FILE"; then
    echo "[INFO] DeltaChat app installed successfully."
else
    echo "[ERROR] Failed to install DeltaChat APK."
    exit 1
fi

echo "=== FINISHED DeltaChat setup.sh ==="