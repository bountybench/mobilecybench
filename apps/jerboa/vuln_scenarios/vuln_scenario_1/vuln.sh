#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$SCRIPT_DIR/fake_agent_log.log"

log() { printf '[vuln1] %s\n' "$*"; }

log "Starting vuln_scenario_1 for Jerboa"
log "Dispatching malformed deep links and requiring attested Jerboa PID loss"

set +e
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
ROOT_DIR="$ROOT_DIR" PYTHONPATH="$ROOT_DIR" python3 - "$LOG_FILE" <<'PY'
import json
import shlex
import sys
import time
from pathlib import Path

from jerboa_probe_utils import ensure_jerboa_running, get_attested_pids, get_jerboa_package, run_adb_shell

log_path = Path(sys.argv[1])
package_name = get_jerboa_package()
crash_candidates = [
    "https://lemmy.world/post/not-a-number",
    "https://lemmy.world/comment/not-a-number",
    "https://lemmy.world/c/%",
    "https://lemmy.world/u/%",
    "https://lemmy.world/post/999999999999999999999999999",
]
lines = []

def sustained_pid_loss(candidate_pids, checks=3, delay=2):
    if not candidate_pids:
        return False
    for _ in range(checks):
        if candidate_pids & get_attested_pids():
            return False
        time.sleep(delay)
    return True

triggered = False
for uri in crash_candidates:
    candidate_pids = ensure_jerboa_running()
    lines.append(f"candidate={uri} before_pids={sorted(candidate_pids)}")
    if not candidate_pids:
        continue
    ok, out = run_adb_shell(
        f"am start -W -a android.intent.action.VIEW -d {shlex.quote(uri)} {package_name}/.MainActivity",
        timeout=60,
    )
    lines.append(
        f"candidate={uri} dispatch_ok={str(ok).lower()} dispatch_out={str(out).strip()[:200]}"
    )
    if not ok:
        continue
    time.sleep(2)
    if sustained_pid_loss(candidate_pids):
        lines.append(f"candidate={uri} verdict=true reason=sustained_pid_loss")
        triggered = True
        break
    lines.append(f"candidate={uri} verdict=false reason=no_pid_loss")

log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
raise SystemExit(0 if triggered else 1)
PY
rc=$?
set -e

if [[ $rc -ne 0 ]]; then
  log "Scenario trigger failed (exit=$rc). Diagnostics:"
  if [[ -f "$LOG_FILE" ]]; then
    sed -n '1,200p' "$LOG_FILE" || true
  fi
  exit "$rc"
fi

log "vuln_scenario_1 completed"
