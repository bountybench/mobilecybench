#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="/mobilecybench"
if [[ ! -f "/.dockerenv" ]]; then
    ROOT_DIR="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null)"
fi
source "${ROOT_DIR}/utils/common.sh"

check_dockerd() {
    docker info > /dev/null 2>&1
    return $?
}

log_info "Checking if Docker daemon is already running..."
if check_dockerd; then
    log_info "Docker daemon is already running"
else
    log_info "Starting Docker daemon..."
    dockerd > /var/log/dockerd.log 2>&1 &

    log_info "Waiting for Docker daemon to come up..."
    timeout 30 sh -c "while (! docker info > /dev/null 2>&1); do sleep 1; done"
    if [ $? -ne 0 ]; then
        log_error "Docker daemon failed to start within 30 seconds."
        cat /var/log/dockerd.log
        exit 1
    fi
    log_info "Docker daemon is running."
fi

log_info "Starting main process: $*"
exec "$@"