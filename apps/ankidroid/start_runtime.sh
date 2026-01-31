#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "ankidroid" "$@")
cd "$SCRIPT_DIR"

adb uninstall com.ichi2.anki >/dev/null 2>&1 || true
adb_install_apk "$APK_PATH"
log_info "AnkiDroid installed successfully."
