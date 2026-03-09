#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

# Waits for a container to become healthy.
wait_healthy() {
    local container=${1:?container required}
    local timeout=${2:-60}
    local elapsed=0
    local health_json=$(docker inspect --format='{{json .State.Health}}' "$container" 2>/dev/null) || health_json="null"
    if [ "$health_json" == "null" ] || [ -z "$health_json" ]; then
        log_warn "container '$container' has no healthcheck"
        return 2
    fi
    while true; do
        local status=$(docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null || true)
        if [[ "$status" == "healthy" ]]; then
            return 0
        fi
        if [ "$elapsed" -ge "$timeout" ]; then
            return 1
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
}
