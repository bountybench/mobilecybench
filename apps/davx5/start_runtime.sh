#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "davx5" "$@")
cd "$SCRIPT_DIR"

setup_backend() {
    log_info "Running docker compose..."
    docker compose up -d --wait

    if [ -d "./radicale/data/collection-root" ]; then
        docker exec radicale rm -r /data/collection-root
    fi

    docker exec radicale cp -a /seeding/seed-data /data/collection-root/
    docker exec radicale chown -R 2999:2999 /data/collection-root
}

install_davx5() {
    adb uninstall at.bitfire.davdroid 2>/dev/null || true
    adb install -r -g "$APK_PATH"
    log_info "DAVx5 installed successfully"
}

main() {
    setup_backend
    install_davx5
}

main "$@"
