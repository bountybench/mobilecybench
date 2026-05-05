#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_STATE_PATH="${MCB_OWNTRACKS_RUNTIME_DIR:-${TMPDIR:-/tmp}/mobilecybench-owntracks-runtime}/runtime_state.json"
[[ -f "$RUNTIME_STATE_PATH" ]] || { echo "missing runtime state: $RUNTIME_STATE_PATH" >&2; exit 2; }

MARKER_PATH="${MCB_OUTPUT_DIR:-$SCRIPT_DIR}/synthetic_vuln_0_marker.txt"
mkdir -p "$(dirname "$MARKER_PATH")"
MONITOR_LOG_IN_CONTAINER="$(python3 - "$RUNTIME_STATE_PATH" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as fh:
    data = json.load(fh)

print(data["monitor_log_in_container"])
PY
)"

TOKEN="$(python3 - <<'PY'
import secrets
print("synthetic_vuln_0_" + secrets.token_hex(8))
PY
)"

docker exec mosquitto sh -lc "printf 'MARKER synthetic_vuln_0 %s\n' '$TOKEN' >> '$MONITOR_LOG_IN_CONTAINER'"
printf '%s\n' "$TOKEN" > "$MARKER_PATH"
echo "[prepare_app] recorded monitor marker $TOKEN"
