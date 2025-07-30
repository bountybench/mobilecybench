#!/bin/bash
set -e

echo "[INFO] Removing secret files..."
rm flags.json || true
rm secrets.json || true
rm dump.sql || true

echo "[INFO] Removing evaluating files..."
rm scores.json || true

echo "[INFO] Removing agent log..."
rm agent_log.log || true

echo "[INFO] Cleaning up environment..."
docker-compose down -v
echo "[INFO] Environment cleaned up."

# Remove ADB reverse port forwarding for port 8080 (if any)
echo "[INFO] Removing ADB reverse for port 8080..."
adb reverse --remove tcp:8080 || true

# Clear Bitwarden app data on emulator for complete reset
echo "[INFO] Clearing Bitwarden app data on emulator..."
pkg_name="com.x8bit.bitwarden.dev"
if adb shell pm list packages | grep -q "$pkg_name"; then
    adb shell pm clear "$pkg_name" || true
    echo "[INFO] Cleared Bitwarden app data."
else
    echo "[INFO] Bitwarden app not found on emulator."
fi

echo "[INFO] Removing vw-data directory..."
rm -rf vw-data || true

echo "[INFO] Uninstalling Bitwarden app..."
adb uninstall com.x8bit.bitwarden.dev || true 