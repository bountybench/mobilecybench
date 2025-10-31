#!/bin/bash
set -e

# DeltaChat Android setup script
#
# Architecture compatibility:
# DeltaChat APK supports multiple architectures: arm64-v8a, armeabi-v7a, x86, and x86_64
# The APK will work with any of these emulator architectures, including x86 (commonly used in CI).
# The Android system automatically selects the appropriate native libraries at runtime.

DELTACHAT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MOBILECYBENCH_ROOT="$(cd "$DELTACHAT_DIR/../.." && pwd)"

echo "=== DeltaChat setup ==="

docker compose -f "$DELTACHAT_DIR/docker-compose.yml" up --build -d

# Wait for Greenmail container to be healthy
echo "Waiting for Greenmail services to start..."
for i in {1..30}; do
    health=$(docker inspect --format='{{.State.Health.Status}}' deltachat-greenmail 2>/dev/null || echo "starting")
    if [ "$health" = "healthy" ]; then
        echo "Greenmail container is healthy"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "[WARNING] Greenmail container not healthy after 60s. Proceeding anyways."
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
