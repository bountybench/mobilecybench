#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_PREFIX="[cleanup]"

info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*"; }

info "Cleaning up Element X Android environment..."

# Take down Docker containers and remove volumes
info "Stopping and removing containers..."
cd "$SCRIPT_DIR"
if [ -f docker-compose.yml ]; then
    docker-compose down -v --remove-orphans 2>/dev/null || warn "Failed to stop some containers"
else
    warn "docker-compose.yml not found, skipping container cleanup"
fi

# Kill any remaining containers with element-x-android prefix
info "Cleaning up any remaining containers..."
docker ps -a --format "table {{.Names}}" | grep -E "(matrix-app|matrix-postgres)" | xargs -r docker rm -f 2>/dev/null || true

# Remove log files
info "Removing log files..."
rm -f setup.log
rm -f fake_agent_log.log

# Remove synapse data directory (but preserve config template)
info "Cleaning synapse data..."
if [ -d "${SCRIPT_DIR}/synapse" ]; then
    # Keep homeserver.yaml template but remove data files
    find "${SCRIPT_DIR}/synapse" -name "*.db" -delete 2>/dev/null || true
    find "${SCRIPT_DIR}/synapse" -name "*.log*" -delete 2>/dev/null || true
    find "${SCRIPT_DIR}/synapse" -name "*.pid" -delete 2>/dev/null || true
    rm -rf "${SCRIPT_DIR}/synapse/media_store" 2>/dev/null || true
    rm -f "${SCRIPT_DIR}/synapse"/*.key 2>/dev/null || true
fi

# Remove Docker volumes
info "Removing Docker volumes..."
docker volume ls --format "table {{.Name}}" | grep element-x-android | xargs -r docker volume rm 2>/dev/null || true

# Clean up Docker networks (but don't remove shared_net as it may be used by other apps)
info "Cleaning up Docker networks..."
docker network ls --format "table {{.Name}}" | grep -E "element-x-android.*private" | xargs -r docker network rm 2>/dev/null || true

# Remove any APK build artifacts from previous runs (optional)
info "Cleaning build artifacts..."
if [ -d "${SCRIPT_DIR}/codebase" ]; then
    find "${SCRIPT_DIR}/codebase" -name "*.apk" -path "*/build/outputs/*" -delete 2>/dev/null || true
fi

info "✅ Cleanup completed successfully!"