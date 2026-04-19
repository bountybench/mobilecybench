#!/usr/bin/env bash
# apps/bitwarden/prepare_victim.sh
# Standardized victim preparation for Bitwarden

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"

echo "INFO: Preparing Bitwarden victim user..."
python3 -u -m apps.bitwarden.victim_login
echo "INFO: Bitwarden victim preparation complete."
