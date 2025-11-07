#!/bin/bash
set -e

DELTACHAT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MOBILECYBENCH_ROOT="$(cd "$DELTACHAT_DIR/../.." && pwd)"

echo "=== DeltaChat setup ==="

docker compose -f "$DELTACHAT_DIR/docker-compose.yml" up --build -d

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
    sleep 1
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

METADATA_FILE="$DELTACHAT_DIR/metadata.json"
PACKAGE_NAME=$(jq -r '.package_name' "$METADATA_FILE" 2>/dev/null)
if [[ -z "$PACKAGE_NAME" || "$PACKAGE_NAME" == "null" ]]; then
    echo "[ERROR] package_name not found in metadata.json"
    exit 1
fi

if ! adb devices | grep -q "device$"; then
    echo "[ERROR] No Android emulator detected"
    exit 1
fi

echo "Installing APK for package: $PACKAGE_NAME"
if ! adb install -r "$APK_FILE"; then
    echo "[ERROR] Failed to install APK."
    exit 1
fi

sleep 2

if ! adb shell pm list packages | grep -q "package:$PACKAGE_NAME"; then
    echo "[ERROR] Package $PACKAGE_NAME is not installed after setup.sh"
    echo "This indicates the APK installation failed silently"
    echo "Checking installed packages:"
    adb shell pm list packages | grep -i deltachat || echo "No deltachat packages found"
    adb shell pm list packages | grep -i messenger || echo "No messenger packages found"
    exit 1
fi

echo "Successfully verified package $PACKAGE_NAME is installed"
echo "=== DeltaChat setup complete ==="
