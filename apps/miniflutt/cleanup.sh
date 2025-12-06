#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${ROOT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
COMPOSE_FILE="${PROJECT_ROOT}/apps/miniflutt/docker-compose.yml"

echo "[cleanup] Cleaning up Android emulator APKs..."

if command -v adb >/dev/null 2>&1; then
    echo "[cleanup] Checking if miniflutt is installed..."
    if adb shell pm list packages | grep -q "be.martinelli.miniflutt"; then
        echo "[cleanup] Uninstalling miniflutt..."
        adb uninstall be.martinelli.miniflutt || true
    else
        echo "[cleanup] miniflutt not installed — nothing to remove."
    fi
else
    echo "[cleanup] adb not found — cannot uninstall APK."
fi

echo "[cleanup] Cleaning Docker containers..."
docker rm -f miniflux-app miniflux-db >/dev/null 2>&1 || true
docker network rm miniflutt_private_net shared_net >/dev/null 2>&1 || true

echo "[cleanup] Cleanup complete."

echo "[cleanup] Stopping and removing docker-compose services..."
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    docker compose -f "${ROOT_DIR}/docker-compose.yml" down --remove-orphans || true
else 
    echo "[cleanup] no docker found"
    exit 1
fi 

echo "[cleanup] Stopping Docker"
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  docker compose -f "$COMPOSE_FILE" down --remove-orphans --volumes || true
elif command -v docker-compose >/dev/null 2>&1; then
  docker-compose -f "$COMPOSE_FILE" down --remove-orphans --volumes || true
else
  echo "[cleanup] WARNING: docker compose / docker-compose not found; skipping compose cleanup."
fi


echo "[cleanup] Cleaning build artifacts from codebase..."
CODEBASE_DIR="${ROOT_DIR}/codebase"

# Flutter/Android build directories
rm -rf "${CODEBASE_DIR}/build" || true
rm -rf "${CODEBASE_DIR}/.dart_tool" || true
rm -rf "${CODEBASE_DIR}/android/app/build" || true

echo "[cleanup] Removing temporary APK build files (but keeping final APK)..."
APK_DIR="${ROOT_DIR}/apps/miniflutt/apk"

# Remove temp/intermediates but NOT miniflutt.apk
find "${APK_DIR}" -type f \( -name "*aligned.apk" -o -name "*unsigned.apk" -o -name "app-release.apk" \) -exec rm -f {} \; || true

echo "[cleanup] Removing temporary signing keys (if any)..."
rm -f "${ROOT_DIR}/various/miniflutt-release.keystore" || true

echo "[cleanup] Cleanup complete."