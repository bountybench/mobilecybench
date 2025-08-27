#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Removing created files..."
rm -rf local.properties || true
rm -rf scores.json || true

echo "Cleanup complete."