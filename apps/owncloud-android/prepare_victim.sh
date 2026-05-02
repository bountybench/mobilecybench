#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Workflow contract: positional $1 = username (optional). Password is taken
# from MCB_VICTIM_PASSWORD when present; otherwise prepare_victim.py falls
# back to its own argparse default. Mirrors the positional-username shape
# nextcloud-talk uses so the workflow drives both apps the same way.
ARGS=()
if [ $# -ge 1 ]; then
    ARGS+=(--username "$1")
fi
if [ -n "${MCB_VICTIM_PASSWORD:-}" ]; then
    ARGS+=(--password "$MCB_VICTIM_PASSWORD")
fi
python3 "$SCRIPT_DIR/prepare_victim.py" "${ARGS[@]}"
