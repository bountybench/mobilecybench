#!/usr/bin/env bash
set -euo pipefail

RUNTIME_STATE_PATH="${MCB_OWNTRACKS_RUNTIME_DIR:-${RUNNER_TEMP:-${TMPDIR:-/tmp}}/mobilecybench-owntracks-runtime}/runtime_state.json"
[[ -f "$RUNTIME_STATE_PATH" ]] || { echo "missing runtime state: $RUNTIME_STATE_PATH" >&2; exit 2; }
PKG="$(python3 - "$RUNTIME_STATE_PATH" <<'PY'
import json, sys
with open(sys.argv[1], "r", encoding="utf-8") as fh:
    data = json.load(fh)
print(data["package_name"])
PY
)"

timeout 20 adb shell am force-stop "$PKG" >/dev/null 2>&1 || true
