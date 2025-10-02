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
            docker-compose down -v 2>/dev/null || warn "Failed to stop some services"

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
    info "Cleaning up temporary files"

    # Remove server directory
    local server_dir="$SCRIPT_DIR/funkwhale-server"
    if [ -d "$server_dir" ]; then
        info "Removing server directory..."
        rm -rf "$server_dir" && info "Removed server directory"
    fi

    # Remove secrets file
    [ -f "$SCRIPT_DIR/secrets.json" ] && rm -f "$SCRIPT_DIR/secrets.json" && info "Removed secrets.json"

    # Note: APK files in apps/funkwhale/apk/ are preserved for future installations
    # To clean build artifacts, run: cd codebase && ./gradlew clean

    info "File cleanup completed"
}

uninstall_app(){
    info "Uninstalling Funkwhale app from emulator/device"

    if command_exists adb && adb get-state >/dev/null 2>&1; then
        # Try to uninstall the app
        adb uninstall audio.funkwhale.ffa 2>/dev/null && info "App uninstalled" || warn "App may not be installed"
    else
        warn "No device connected or ADB not available"
    fi
}

main(){
    info "Starting Funkwhale cleanup"

    # Stop Docker services and remove containers
    cleanup_docker

    # Clean up temporary files
    cleanup_files

    # Uninstall app from device
    uninstall_app

    info "Funkwhale cleanup completed!"
    echo ""
    echo "All Docker containers, networks, and temporary files have been removed."
    echo "To restart the setup, run: ./setup.sh"
}

# Run main function
main "$@"