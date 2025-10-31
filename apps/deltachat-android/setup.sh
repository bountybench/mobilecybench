#!/bin/bash
set -e

# DeltaChat Android setup script
#
# Note on architecture requirements:
# While DeltaChat APK includes native libraries for multiple architectures (arm64-v8a, armeabi-v7a, x86_64),
# the testing environment may require specific architecture matching between the APK and emulator.
# If you encounter installation issues, ensure your emulator architecture matches the APK's primary ABI.

DELTACHAT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MOBILECYBENCH_ROOT="$(cd "$DELTACHAT_DIR/../.." && pwd)"

echo "=== DeltaChat setup ==="

docker compose -f "$DELTACHAT_DIR/docker-compose.yml" up --build -d

# Wait for Greenmail to be ready (no healthcheck available in container)
echo "Waiting for Greenmail services to start..."
for i in {1..30}; do
    # Check if container is running
    if docker ps | grep -q deltachat-greenmail; then
        # Try to connect to SMTP port to verify service is ready
        if nc -z localhost 1025 2>/dev/null; then
            echo "Greenmail SMTP service is ready"
            break
        fi
    fi
    if [ $i -eq 30 ]; then
        echo "[WARNING] Greenmail may not be fully ready after 60s. Proceeding anyways."
    fi
    sleep 2
done

cd "$MOBILECYBENCH_ROOT"
python3 "${DELTACHAT_DIR}/create_accounts.py"
if [ $? -ne 0 ]; then
  echo "[ERROR] Email account creation failed."
  exit 1
fi

APK_FILE="${DELTACHAT_DIR}/apk/deltachat-android.apk"
if [[ ! -f "$APK_FILE" ]]; then
    echo "[ERROR] APK not found"
    echo "[ERROR] Run setup_app_source.sh or setup_app_apklink.sh first"
    exit 1
fi

if ! adb devices | grep -q "device$"; then
    echo "[ERROR] No Android emulator detected"
    exit 1
fi

if ! adb install -r "$APK_FILE"; then
    echo "[ERROR] Failed to install APK."
    exit 1
fi

echo "=== DeltaChat setup complete ==="
