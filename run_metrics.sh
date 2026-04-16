#!/bin/bash

# Standalone runtime metrics collection that does not affect scoring.
set -euo pipefail

app_path="$(realpath "$1")"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d "$app_path" ]; then
    echo "ERROR: App path '$app_path' is not a directory." >&2
    exit 1
fi

PYTHON=$("${SCRIPT_DIR}/utils/detect_python.sh")

"$PYTHON" "${SCRIPT_DIR}/utils/crash_metrics.py" "$app_path"
