#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_PREFIX="[cleanup]"

info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*"; }

info "Cleaning up Element X Android environment..."

cd "$SCRIPT_DIR"

# Stop Docker containers and clean database
info "Stopping containers and cleaning database..."
if [[ -f docker-compose.yml ]]; then
    # First, clean the database before stopping containers
    info "Cleaning Matrix database..."
    docker-compose exec -T matrix-postgres psql -U synapse -d synapse -c "
        DELETE FROM users WHERE name LIKE '@agent%' OR name LIKE '@alice%' OR name LIKE '@bob%' OR name LIKE '@admin%';
        DELETE FROM access_tokens;
        DELETE FROM refresh_tokens;
        DELETE FROM user_filters;
        DELETE FROM pusher_throttle;
    " 2>/dev/null || true
    
    # Now stop everything and remove volumes
    docker-compose down -v --remove-orphans 2>/dev/null || warn "Failed to stop some containers"
fi

# Remove specific containers and volumes
docker ps -a --format "{{.Names}}" | grep -E "matrix-(app|postgres)" | xargs -r docker rm -f 2>/dev/null || true

# Remove persistent volumes completely
info "Removing volumes..."
for vol in element-x-android_matrix_postgres_data matrix_postgres_data postgres_data; do
    docker volume rm -f "$vol" 2>/dev/null || true
done

# Remove networks
docker network ls --format "{{.Name}}" | grep "element-x-android.*private" | xargs -r docker network rm 2>/dev/null || true

# Clean local files
info "Cleaning local files..."
rm -f setup.log setup_app_source.log
rm -rf synapse/*.db synapse/*.log* synapse/*.pid synapse/media_store synapse/*.key 2>/dev/null || true
find codebase -name "*.apk" -path "*/build/outputs/*" -delete 2>/dev/null || true

info "✅ Cleanup completed!"