#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APK_PATH="${SCRIPT_DIR}/apk/davx5.apk"

cd "${SCRIPT_DIR}"

setup_backend() {

    echo "Running docker compose..."
    docker compose up -d --wait

    if [ -d "./radicale/data/collection-root" ]; then
        docker exec radicale rm -r /data/collection-root
    fi

    docker exec radicale cp -a /seeding/seed-data /data/collection-root/
    docker exec radicale chown -R 2999:2999 /data/collection-root

}

install_davx5() {
    adb wait-for-device

    adb uninstall at.bitfire.davdroid 2>/dev/null || echo "No existing installation found"

    adb install -r -g "$APK_PATH"
    echo "DAVx5 installed successfully"
}

main() {
    setup_backend
    install_davx5
}

main "$@"