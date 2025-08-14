#!/bin/bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$ROOT_DIR/docker-compose.yml"

if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "Compose file not found: $COMPOSE_FILE" >&2
  exit 1
fi

echo "Bringing down NewPipe Docker environment."
docker compose -f "$COMPOSE_FILE" down --remove-orphans

echo "Removing generated files..."
rm -rf scores.json || true
rm -f newpipe_local_repo.gradle || true
rm -f ca-cert.pem || true
rm -f *.0 || true
rm -rf flows || true
rm -rf NewPipeExtractor || true

# Clean up external storage leaks from vuln scenarios
if command -v adb &> /dev/null && adb devices | grep -q "device\|emulator"; then
    echo "Cleaning up external storage leaks..."
    adb shell "rm -f /sdcard/backup_newpipe_data.db" 2>/dev/null || true
    adb shell "rm -f /sdcard/newpipe.db" 2>/dev/null || true  
    adb shell "rm -f /sdcard/leaked_newpipe.sqlite" 2>/dev/null || true
fi

echo "NewPipe environment cleanup complete."