#!/bin/bash
# Stop the MobileCybench Orchestrator container

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "============================================"
echo "Stopping MobileCybench Orchestrator"
echo "============================================"

cd "$PROJECT_ROOT"

# Stop using docker-compose
docker-compose -f docker-compose.orchestrator.yml down

echo ""
echo "✓ Orchestrator stopped"
echo ""
