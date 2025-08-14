#!/bin/bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$ROOT_DIR/docker-compose.yml"

echo "Bringing down NewPipe Docker environment."
# Try to stop containers even if compose file doesn't exist
docker stop newpipe_proxy 2>/dev/null || true
docker rm newpipe_proxy 2>/dev/null || true
docker volume rm newpipe_proxy_data 2>/dev/null || true

if [[ -f "$COMPOSE_FILE" ]]; then
  docker compose -f "$COMPOSE_FILE" down --remove-orphans --volumes 2>/dev/null || true
fi

echo "Removing generated files..."
rm -rf scores.json || true
rm -f newpipe_local_repo.gradle || true
rm -f ca-cert.pem || true
rm -f *.0 || true
rm -rf flows || true
rm -rf NewPipeExtractor || true

# Clean up external storage leaks from vuln scenarios
if command -v adb &> /dev/null && adb devices 2>/dev/null | grep -q "device\|emulator"; then
    echo "Cleaning up external storage leaks..."
    adb shell "rm -f /sdcard/backup_newpipe_data.db" 2>/dev/null || true
    adb shell "rm -f /sdcard/newpipe.db" 2>/dev/null || true  
    adb shell "rm -f /sdcard/leaked_newpipe.sqlite" 2>/dev/null || true
    adb shell "rm -rf /sdcard/Android/data/leaked_newpipe.sqlite" 2>/dev/null || true
    
    # Clean up any other potential leaked files
    adb shell "find /sdcard -name '*newpipe*' -type f" 2>/dev/null | while read file; do
        if [[ "$file" != *"/Android/data/org.schabi.newpipe.debug.HEAD/"* ]]; then
            adb shell "rm -f '$file'" 2>/dev/null || true
        fi
    done
    
    # Reset app state
    echo "Resetting app state..."
    PKG="org.schabi.newpipe.debug.HEAD"
    adb shell "am force-stop $PKG" 2>/dev/null || true
    adb shell "pm clear $PKG" 2>/dev/null || true
    
    # Clear ANR traces if accessible
    adb root 2>/dev/null && adb shell "rm -f /data/anr/traces.txt" 2>/dev/null || true
    
    # Reset proxy settings
    echo "Resetting proxy settings..."
    adb shell settings delete global http_proxy 2>/dev/null || true
    adb shell settings delete global https_proxy 2>/dev/null || true
fi

echo "NewPipe environment cleanup complete."