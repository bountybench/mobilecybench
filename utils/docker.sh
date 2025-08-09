#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

# Runs 'docker-compose up -d' for the given services.
docker_compose_up() {
    require_cmd docker-compose
    log_info "docker-compose up -d $*"
    docker-compose up -d "$@"
}

# Runs 'docker-compose down -v' for the given services.
docker_compose_down() {
    require_cmd docker-compose
    log_info "docker-compose down -v $*"
    docker-compose down -v "$@"
}

# Gets the container ID for a given docker-compose service name.
docker_get_container() {
    local service=$1
    if [[ -z "$service" ]]; then
        fatal "docker_get_container requires a compose service name"
    fi
    local cid=$(docker-compose ps -q "$service" | head -n1)
    if [[ -z "$cid" ]]; then
        fatal "No container id for service '$service'"
    fi
    printf '%s' "$cid"
}

# Executes a command in a container by service name or container ID.
docker_exec() {
    if [[ $# -lt 2 ]]; then
        fatal "docker_exec <container-or-service> <cmd...>"
    fi
    local target=$1; shift
    local cid=$(docker-compose ps -q "${target}" 2>/dev/null || true)
    if [[ -n "$cid" ]]; then
        docker exec "$cid" "$@"
    else
        docker exec "$target" "$@"
    fi
}

# Waits for a container to become healthy.
wait_healthy() {
    local container=${1:?container required}
    local timeout=${2:-60}
    local elapsed=0
    local health_json=$(docker inspect --format='{{json .State.Health}}' "$container" 2>/dev/null || echo "null")
    if [[ "$health_json" == "null" || -z "$health_json" ]]; then
        return 2
    fi
    while true; do
        local status=$(docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null || true)
        if [[ "$status" == "healthy" ]]; then
            return 0
        fi
        if (( elapsed >= timeout )); then
            return 1
        fi
        sleep 1
        ((elapsed++))
    done
}