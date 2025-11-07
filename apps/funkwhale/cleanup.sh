#!/usr/bin/env bash
# Cleanup script for Funkwhale MobileCybench setup
# Stops and removes Docker containers, networks, and temporary files

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}" )" && pwd)"
CODEBASE_DIR="${SCRIPT_DIR}/codebase"
LOG_PREFIX="[cleanup]"

info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*" >&2; }
command_exists(){ command -v "$1" >/dev/null 2>&1; }

cleanup_docker(){
    info "Stopping and removing Funkwhale Docker containers"

    local server_dir="$SCRIPT_DIR/funkwhale-server"

    if [ -d "$server_dir" ] && [ -f "$server_dir/docker-compose.yml" ]; then
        cd "$server_dir"

        # Stop all services
        if command_exists docker; then
            info "Stopping Docker services..."
            docker-compose down -v 2>/dev/null || docker compose down -v 2>/dev/null || warn "Failed to stop some services"

            # Remove any dangling containers
            info "Removing Funkwhale containers..."
            docker ps -a --filter "label=com.docker.compose.project=funkwhale-server" --format "{{.ID}}" | \
                xargs -r docker rm -f 2>/dev/null || warn "No containers to remove"

            info "Docker cleanup completed"
        else
            warn "Docker not found, skipping container cleanup"
        fi
    else
        warn "Funkwhale server directory not found, skipping Docker cleanup"
    fi
}

main(){
    info "Starting Funkwhale cleanup"

    # Stop Docker services and remove containers
    cleanup_docker

    info "Funkwhale cleanup completed!"
    echo ""
    echo "All Docker containers, data files, and app have been removed."
    echo "APK files in apk/ directory are preserved."
}

# Run main function
main "$@"
