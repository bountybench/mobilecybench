#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

compose_down() {
    if docker compose version >/dev/null 2>&1; then
        docker compose -f "$SCRIPT_DIR/docker-compose.yml" down -v --remove-orphans 2>/dev/null || true
    fi
}

echo "Cleaning up Termux test environment..."

compose_down

if ! adb devices | grep -q "emulator"; then
    echo "No emulator found, skipping app cleanup"
else
    if adb shell pm list packages | grep -q "com.termux"; then
        echo "Uninstalling Termux app..."
        adb uninstall com.termux
    fi

    echo "Clearing device logs..."
    adb logcat -c >/dev/null 2>&1 || true
    adb shell su 0 rm -f /data/local/tmp/mcb_termux_setup_anchor /data/local/tmp/mcb_termux_seed_manifest.json >/dev/null 2>&1 || true
    adb shell su 0 rm -rf /sdcard/Download/mobilecybench-termux >/dev/null 2>&1 || true
fi

if [ -d "$SCRIPT_DIR/codebase" ]; then
    echo "Cleaning build artifacts..."
    cd "$SCRIPT_DIR/codebase"
    ./gradlew clean >/dev/null 2>&1 || true
fi

echo "Removing generated files..."
rm -rf "$SCRIPT_DIR/local_repo/repo"
rm -f "$SCRIPT_DIR/scores.json" "$SCRIPT_DIR/exploit_evidence.txt"
find "$SCRIPT_DIR" -name "*.stolen" -delete
find "$SCRIPT_DIR" -type f -name "*.log" -delete
find "$SCRIPT_DIR" -type f -name "*.txt" -not -name "secrets.json" -delete

echo "Cleanup completed successfully!"
