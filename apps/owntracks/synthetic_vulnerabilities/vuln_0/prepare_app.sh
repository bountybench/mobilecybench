#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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

TOKEN="$(python3 - <<'PY'
import secrets
print("synthetic_vuln_0_" + secrets.token_hex(8))
PY
)"

docker exec "$MOSQUITTO_CONTAINER_NAME" sh -lc "printf 'MARKER synthetic_vuln_0 %s\n' '$TOKEN' >> '$MONITOR_LOG_IN_CONTAINER'"
printf '%s\n' "$TOKEN" > "$MARKER_PATH"
echo "[prepare_app] recorded monitor marker $TOKEN"
