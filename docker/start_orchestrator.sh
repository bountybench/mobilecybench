#!/bin/bash
# Start the MobileCybench Orchestrator container

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "============================================"
echo "Starting MobileCybench Orchestrator"
echo "============================================"

cd "$PROJECT_ROOT"

# Check if Docker is running
if ! docker info >/dev/null 2>&1; then
    echo "Error: Docker is not running. Please start Docker and try again."
    exit 1
fi

# Check if image exists
if ! docker image inspect mobilecybench-orchestrator:latest >/dev/null 2>&1; then
    echo "Error: Orchestrator image not found. Please build it first:"
    echo "  ./docker/build_orchestrator.sh"
    exit 1
fi

# Check if KVM is available (for hardware acceleration)
if [ ! -e /dev/kvm ]; then
    echo "Warning: /dev/kvm not found. Emulator will run without hardware acceleration."
    echo "This will significantly impact performance."
    KVM_DEVICE=""
else
    echo "✓ KVM hardware acceleration available"
    KVM_DEVICE="--device /dev/kvm"
fi

# Load environment variables from .env if it exists
if [ -f "$PROJECT_ROOT/.env" ]; then
    echo "Loading environment variables from .env..."
    export $(grep -v '^#' "$PROJECT_ROOT/.env" | xargs)
fi

# Start the orchestrator using docker-compose
echo "Starting orchestrator container..."
docker-compose -f docker-compose.orchestrator.yml up -d

echo ""
echo "============================================"
echo "Orchestrator started!"
echo "============================================"
echo ""
echo "Container name: mobilecybench-orchestrator"
echo ""
echo "Useful commands:"
echo "  Exec into container:  docker exec -it mobilecybench-orchestrator bash"
echo "  View logs:            docker logs -f mobilecybench-orchestrator"
echo "  Stop orchestrator:    ./docker/stop_orchestrator.sh"
echo "  Check status:         docker ps | grep mobilecybench-orchestrator"
echo ""
echo "To run experiments inside the container:"
echo "  docker exec -it mobilecybench-orchestrator bash"
echo "  Then inside the container:"
echo "    ./setup.sh <app_name>           # Set up emulator for app"
echo "    ./start_emulator.sh             # Start emulator"
echo "    python3 runner.py <app_name>    # Run experiment"
echo ""
