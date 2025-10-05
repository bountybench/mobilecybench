#!/bin/bash
# Build the MobileCybench Orchestrator container

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "============================================"
echo "Building MobileCybench Orchestrator"
echo "============================================"

cd "$PROJECT_ROOT"

# Check if Docker is running
if ! docker info >/dev/null 2>&1; then
    echo "Error: Docker is not running. Please start Docker and try again."
    exit 1
fi

# Build the orchestrator image
echo "Building orchestrator image..."
docker build --no-cache -f Dockerfile.orchestrator -t mobilecybench-orchestrator:latest .

# Check if shared_net network exists, create if not
if ! docker network inspect shared_net >/dev/null 2>&1; then
    echo "Creating shared_net network..."
    docker network create shared_net
else
    echo "✓ shared_net network already exists"
fi

echo ""
echo "============================================"
echo "Build complete!"
echo "============================================"
echo ""
echo "Next steps:"
echo "  1. Start the orchestrator: ./docker/start_orchestrator.sh"
echo "  2. Or use docker-compose: docker-compose -f docker-compose.orchestrator.yml up -d"
echo ""
