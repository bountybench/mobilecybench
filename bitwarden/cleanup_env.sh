#!/bin/bash
set -e

echo "Removing secret files..."
rm -f initdb/seed.sql
rm -f accounts.json
rm -f logins.txt

echo "[INFO] Cleaning up environment..."
docker-compose down -v
echo "[INFO] Environment cleaned up."

# Remove ADB reverse port forwarding for port 8080 (if any)
echo "[INFO] Removing ADB reverse for port 8080..."
adb reverse --remove tcp:8080 || true

echo "[INFO] Shutting down any process using localhost:8080..."
# Find and kill any process using port 8080 (ignore errors if none found)
if lsof -i :8080 -sTCP:LISTEN -t >/dev/null; then
  lsof -i :8080 -sTCP:LISTEN -t | xargs kill -9 || true
  echo "[INFO] Closed processes on port 8080."
else
  echo "[INFO] No process found on port 8080."
fi

# Clear Bitwarden app data on emulator for complete reset
echo "[INFO] Clearing Bitwarden app data on emulator..."
pkg_name="com.x8bit.bitwarden.dev"
if adb shell pm list packages | grep -q "$pkg_name"; then
    adb shell pm clear "$pkg_name" || true
    echo "[INFO] Cleared Bitwarden app data."
else
    echo "[INFO] Bitwarden app not found on emulator."
fi

rm -rf vw-data

rm -f db_dump.sql