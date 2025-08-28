#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Removing created files..."
rm -rf $SCRIPT_DIR/local.properties || true
rm -rf $SCRIPT_DIR/scores.json || true

echo "Cleanup complete."