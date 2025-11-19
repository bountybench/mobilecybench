#!/usr/bin/env bash
# Grocy cleanup - remove all containers, volumes, data, and generated files
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_PREFIX="[cleanup]"
METADATA_FILE="$SCRIPT_DIR/metadata.json"

info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*"; }

# Check if docker command exists (but don't fail if not available)
if ! command -v docker >/dev/null 2>&1; then
    warn "Docker not found on PATH, skipping Docker cleanup"
    DOCKER_AVAILABLE=false
else
    DOCKER_AVAILABLE=true
fi

# Check if adb command exists
if ! command -v adb >/dev/null 2>&1; then
    ADB_AVAILABLE=false
else
    ADB_AVAILABLE=true
fi

info "Cleaning up Grocy environment..."

cd "$SCRIPT_DIR"

# Uninstall Android app if installed
if [ "$ADB_AVAILABLE" = "true" ]; then
    # Read package name from metadata.json
    if [ -f "$METADATA_FILE" ]; then
        PACKAGE_NAME=$(python3 -c "import json; print(json.load(open('$METADATA_FILE'))['package_name'])" 2>/dev/null || echo "")
        if [ -n "$PACKAGE_NAME" ]; then
            info "Uninstalling Android app: $PACKAGE_NAME"
            adb uninstall "$PACKAGE_NAME" 2>/dev/null || true
        fi
    fi
    # Also try to uninstall both release and debug versions
    adb uninstall xyz.zedler.patrick.grocy 2>/dev/null || true
    adb uninstall xyz.zedler.patrick.grocy.debug 2>/dev/null || true
fi

# Stop and remove Docker containers and volumes
if [ "$DOCKER_AVAILABLE" = "true" ]; then
    info "Stopping containers and removing volumes..."
    if [ -f docker-compose.yml ]; then
        docker compose -f docker-compose.yml down -v --remove-orphans 2>/dev/null || true
    fi

    # Remove specific containers if they exist
    info "Removing Grocy containers..."
    docker ps -a --format "{{.Names}}" 2>/dev/null | grep -E "grocy-app" | xargs -r docker rm -f 2>/dev/null || true

    # Remove persistent volumes
    info "Removing Docker volumes..."
    for vol in grocy_grocy_data grocy_data; do
        docker volume rm -f "$vol" 2>/dev/null || true
    done

    # Remove networks
    info "Removing Docker networks..."
    docker network ls --format "{{.Name}}" 2>/dev/null | grep "grocy" | xargs -r docker network rm 2>/dev/null || true
else
    info "Skipping Docker cleanup (Docker not available)"
fi

# Clean local directories and files
info "Cleaning local files..."
rm -rf dist/ 2>/dev/null || true
# NOTE: Keep apk/ directory structure but may clean contents if needed between tests
rm -rf logs/ 2>/dev/null || true
rm -f .env 2>/dev/null || true
rm -f scores.json 2>/dev/null || true

# Clean Python cache directories
rm -rf __pycache__/ 2>/dev/null || true
find . -name "*.pyc" -delete 2>/dev/null || true
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

# Clean any stale temp files from previous CI runs
rm -f /tmp/grocy_test.log 2>/dev/null || true

# Clean build artifacts from codebase
if [ -d codebase ]; then
    info "Cleaning build artifacts..."
    find codebase -name "*.apk" -path "*/build/outputs/*" -delete 2>/dev/null || true
    # More specific build directory cleanup
    if [ -d "codebase/app/build" ]; then
        rm -rf codebase/app/build 2>/dev/null || true
    fi
    # Remove Gradle cache
    rm -rf codebase/.gradle 2>/dev/null || true
fi

info "✅ Cleanup completed!"

exit 0


