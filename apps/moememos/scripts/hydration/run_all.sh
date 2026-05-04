#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

"$SCRIPT_DIR/run_backend.sh"
"$SCRIPT_DIR/run_victim.sh"

python3 "$SCRIPT_DIR/hydrate.py" write-manifest
printf '[hydration] complete\n'
