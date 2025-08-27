#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "${SCRIPT_DIR}/utils.sh"
set +e

crash_servers() {
    log_info "Crashing web servers..."
    docker kill wordpress-db >/dev/null 2>&1
    docker kill wordpress-app >/dev/null 2>&1
}

crash_app() {
    log_info "Crashing Android application..."
    # Crash twice to bypass exception handling
    adb shell am crash org.wordpress.android
    adb shell am crash org.wordpress.android
}

main() {
    crash_servers
    crash_app
}

main "$@"