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

cleanup_files(){
    info "Cleaning up data files"

    local server_dir="$SCRIPT_DIR/funkwhale-server"

    # Remove data directories (postgres, redis, media, etc.)
    if [ -d "$server_dir/data" ]; then
        info "Removing data directories..."
        rm -rf "$server_dir/data" || {
            rm -rf "$server_dir/data" || warn "Failed to remove data directory"
        }

        # Verify removal
        if [ -d "$server_dir/data" ]; then
            warn "Data directory still exists after cleanup attempt"
        fi
    fi

    # Remove typesense data
    if [ -d "$server_dir/typesense" ]; then
        info "Removing typesense data..."
        rm -rf "$server_dir/typesense" || rm -rf "$server_dir/typesense" || warn "Failed to remove typesense data"
    fi

    # Remove generated .env file
    if [ -f "$server_dir/.env" ]; then
        info "Removing .env file..."
        rm -f "$server_dir/.env"
    fi

    info "File cleanup completed"
}

main(){
    info "Starting Funkwhale cleanup"

    # Stop Docker services and remove containers
    cleanup_docker

    # Clean up data files
    cleanup_files

    info "Funkwhale cleanup completed!"
    echo ""
    echo "All Docker containers, data files, and app have been removed."
    echo "APK files in apk/ directory are preserved."
    echo "To restart the setup, run: ./setup.sh"
}

# Run main function
main "$@"