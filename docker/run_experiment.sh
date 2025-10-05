#!/bin/bash
# MobileCybench Automated Experiment Runner
# Run this script from the HOST to automatically build, start, and run experiments
# Usage: ./docker/run_experiment.sh <app_name> [config_file] [--keep-running]

set -e
set -o pipefail

# --- Configuration ---
CONTAINER_NAME="mobilecybench-backend"
COMPOSE_FILE="docker-compose.yml"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- Colors for output ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# --- Helper Functions ---
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

usage() {
    echo "Usage: $0 <app_name> [config_file] [--keep-running]"
    echo ""
    echo "Arguments:"
    echo "  app_name        : Name of the app to test (e.g., audiobookshelf, owncloud-android)"
    echo "  config_file     : Optional config file (default: runner_config.json)"
    echo "  --keep-running  : Keep the container running after experiment completes"
    echo ""
    echo "Examples:"
    echo "  $0 audiobookshelf"
    echo "  $0 owncloud-android custom_config.json"
    echo "  $0 audiobookshelf runner_config.json --keep-running"
    echo ""
    exit 1
}

cleanup() {
    if [[ "$KEEP_RUNNING" == "false" ]]; then
        log_info "Stopping and removing container..."
        cd "$PROJECT_ROOT"
        docker compose down || true
    else
        log_info "Container left running as requested (use 'docker compose down' to stop)"
    fi
}

# --- Argument Parsing ---
if [ $# -lt 1 ]; then
    log_error "Missing required argument: app_name"
    usage
fi

APP_NAME="$1"
CONFIG_FILE="${2:-runner_config.json}"
KEEP_RUNNING="false"

# Check for --keep-running flag
for arg in "$@"; do
    if [[ "$arg" == "--keep-running" ]]; then
        KEEP_RUNNING="true"
    fi
done

# Remove --keep-running from config_file if it was passed there
if [[ "$CONFIG_FILE" == "--keep-running" ]]; then
    CONFIG_FILE="runner_config.json"
fi

log_info "Starting automated experiment for: $APP_NAME"
log_info "Config file: $CONFIG_FILE"
log_info "Keep container running: $KEEP_RUNNING"
echo ""

# --- Navigate to project root ---
cd "$PROJECT_ROOT"

# --- Create required Docker volumes if they don't exist ---
log_info "Checking required Docker volumes..."
if ! docker volume inspect dind-data >/dev/null 2>&1; then
    log_info "Creating dind-data volume..."
    docker volume create dind-data
    log_success "Created dind-data volume"
else
    log_info "dind-data volume already exists"
fi

if ! docker volume inspect gradle-cache >/dev/null 2>&1; then
    log_info "Creating gradle-cache volume..."
    docker volume create gradle-cache
    log_success "Created gradle-cache volume"
else
    log_info "gradle-cache volume already exists"
fi
echo ""

# --- Check if container is already running ---
if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    log_warn "Container $CONTAINER_NAME is already running"
    CONTAINER_EXISTS="true"
else
    CONTAINER_EXISTS="false"
fi

# --- Build the container if needed ---
if [[ "$CONTAINER_EXISTS" == "false" ]]; then
    log_info "Building backend container..."
    docker compose build backend
    log_success "Container built successfully"
    echo ""
fi

# --- Start the container ---
if [[ "$CONTAINER_EXISTS" == "false" ]]; then
    log_info "Starting backend container..."
    docker compose up -d backend

    log_info "Waiting for Docker daemon to start inside container..."

    # Wait for Docker daemon to be ready (up to 60 seconds)
    TIMEOUT=60
    ELAPSED=0
    while [ $ELAPSED -lt $TIMEOUT ]; do
        if docker exec $CONTAINER_NAME docker info >/dev/null 2>&1; then
            log_success "Docker daemon is ready"
            break
        fi
        sleep 2
        ELAPSED=$((ELAPSED + 2))
        echo -n "."
    done
    echo ""

    if [ $ELAPSED -ge $TIMEOUT ]; then
        log_error "Docker daemon failed to start within ${TIMEOUT} seconds"
        log_error "Check container logs: docker logs $CONTAINER_NAME"
        exit 1
    fi

    # Give it a bit more time to stabilize
    sleep 3
    echo ""
else
    log_info "Using existing running container"
    echo ""
fi

# --- Run the experiment inside the container ---
log_info "=========================================="
log_info "Running experiment: $APP_NAME"
log_info "=========================================="
echo ""

# Register cleanup on exit
if [[ "$CONTAINER_EXISTS" == "false" ]]; then
    trap cleanup EXIT
fi

# Execute the internal experiment script (without -it for non-interactive execution)
docker exec $CONTAINER_NAME bash -c "cd /mobilecybench && ./docker/run_experiment_internal.sh '$APP_NAME' '$CONFIG_FILE'"

# Check exit code
if [ $? -eq 0 ]; then
    echo ""
    log_success "=========================================="
    log_success "Experiment completed successfully!"
    log_success "=========================================="
    echo ""
    log_info "Results: ./results/"
    log_info "Logs: ./logs/"
else
    echo ""
    log_error "=========================================="
    log_error "Experiment failed!"
    log_error "=========================================="
    exit 1
fi
