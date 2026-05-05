#!/usr/bin/env bash
set -euo pipefail

RUNTIME_MANIFEST="${TMPDIR:-/tmp}/mobilecybench-owntracks-runtime/runtime_manifest.json"
SCENARIO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_TOOLS="$SCENARIO_DIR/../../runtime_tools.py"
PKG="$(python3 "$RUNTIME_TOOLS" json-field "$RUNTIME_MANIFEST" package_name)"

adb shell am force-stop "$PKG" >/dev/null 2>&1 || true
