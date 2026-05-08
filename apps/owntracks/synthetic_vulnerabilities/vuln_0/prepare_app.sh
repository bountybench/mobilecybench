#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${MCB_APP_DIR:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
RUNTIME_STATE_PATH="${MCB_OWNTRACKS_RUNTIME_DIR:-${RUNNER_TEMP:-${TMPDIR:-/tmp}}/mobilecybench-owntracks-runtime}/runtime_state.json"
[[ -f "$RUNTIME_STATE_PATH" ]] || { echo "missing runtime state: $RUNTIME_STATE_PATH" >&2; exit 2; }

RUNTIME_DIR="$(cd "$(dirname "$RUNTIME_STATE_PATH")" && pwd)"
MARKER_PATH="${MCB_OUTPUT_DIR:-$RUNTIME_DIR}/synthetic_vuln_0_marker.txt"
mkdir -p "$(dirname "$MARKER_PATH")"
MONITOR_LOG_IN_CONTAINER="$(python3 - "$RUNTIME_STATE_PATH" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as fh:
    data = json.load(fh)

print(data["monitor_log_in_container"])
PY
)"
MOSQUITTO_CONTAINER_NAME="$(python3 - "$RUNTIME_STATE_PATH" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as fh:
    data = json.load(fh)

print(data["broker"]["container_name"])
PY
)"

bash "$APP_DIR/prepare_victim.sh"
OFFSET="$(timeout 20 docker exec "$MOSQUITTO_CONTAINER_NAME" sh -lc "wc -l < '$MONITOR_LOG_IN_CONTAINER' 2>/dev/null || echo 0" | awk '{print $1}')"
printf '%s\n' "$OFFSET" > "$MARKER_PATH"
echo "[prepare_app] recorded monitor offset $OFFSET"
