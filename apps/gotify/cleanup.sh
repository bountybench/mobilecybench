#!/usr/bin/env bash
# Gotify cleanup - remove all containers, volumes, data, and generated files
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_PREFIX="[cleanup]"

info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*"; }

# Check if docker command exists (but don't fail if not available)
if ! command -v docker >/dev/null 2>&1; then
    warn "Docker not found on PATH, skipping Docker cleanup"
    DOCKER_AVAILABLE=false
else
    DOCKER_AVAILABLE=true
fi

info "Cleaning up Gotify environment..."

cd "$SCRIPT_DIR"

# Stop and remove Docker containers and volumes
if [ "$DOCKER_AVAILABLE" = "true" ]; then
    info "Stopping containers and removing volumes..."
    if [ -f docker-compose.yml ]; then
        docker compose -f docker-compose.yml down -v --remove-orphans 2>/dev/null || true
    fi

    # Remove specific containers if they exist
    info "Removing Gotify containers..."
    docker ps -a --format "{{.Names}}" 2>/dev/null | grep -E "gotify-(server|db)" | xargs -r docker rm -f 2>/dev/null || true

    # Remove persistent volumes (with proper project prefix)
    info "Removing Docker volumes..."
    for vol in gotify_gotify_data gotify_pg_data postgres_data gotify_data pg_data gotify_gotify-net; do
        docker volume rm -f "$vol" 2>/dev/null || true
    done

    # Remove networks
    info "Removing Docker networks..."
    docker network ls --format "{{.Name}}" 2>/dev/null | grep "gotify" | xargs -r docker network rm 2>/dev/null || true
else
    info "Skipping Docker cleanup (Docker not available)"
fi

# Clean local directories and files
info "Cleaning local files..."
rm -rf dist/ 2>/dev/null || true
rm -rf logs/ 2>/dev/null || true
rm -f .env 2>/dev/null || true

# Clean build artifacts from codebase
if [ -d codebase ]; then
    info "Cleaning build artifacts..."
    find codebase -name "*.apk" -path "*/build/outputs/*" -delete 2>/dev/null || true
    # More specific build directory cleanup
    if [ -d "codebase/app/build" ]; then
        rm -rf codebase/app/build 2>/dev/null || true
    fi
    if [ -d "codebase/client/build" ]; then
        rm -rf codebase/client/build 2>/dev/null || true
    fi
    # Remove Gradle cache
    rm -rf codebase/.gradle 2>/dev/null || true
fi

info "✅ Cleanup completed!"

exit 0