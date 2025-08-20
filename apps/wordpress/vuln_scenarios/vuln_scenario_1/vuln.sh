#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="/mobilecybench"
if [[ -z "$ROOT_DIR" ]]; then 
    ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"; 
fi

source "${ROOT_DIR}/utils/common.sh"
source "${ROOT_DIR}/utils/docker.sh"
source "${ROOT_DIR}/utils/android.sh"
source "${ROOT_DIR}/utils/wait.sh"

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