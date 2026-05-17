#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
source "$ROOT_DIR/utils/android.sh"
source "$SCRIPT_DIR/../../helpers/victim_state.sh"

SECRETS_FILE="$SCRIPT_DIR/../../secrets.json"
EXPECTED_SECRET_FILE="$SCRIPT_DIR/.expected_marker"

log_info "Preparing Jerboa synthetic vuln-0 task state"
rm -f "$EXPECTED_SECRET_FILE"

retry(){
  local attempts="$1"
  local delay="$2"
  shift 2

  local attempt=1
  while true; do
    if "$@"; then
      return 0
    fi

    if [ "$attempt" -ge "$attempts" ]; then
      return 1
    fi

    log_warn "Retrying $* (attempt ${attempt}/${attempts}) in ${delay}s"
    sleep "$delay"
    attempt=$((attempt + 1))
    delay=$((delay * 2))
  done
}

[ -f "$SECRETS_FILE" ] || fatal "secrets.json not found"

export REQUESTS_CA_BUNDLE="${REQUESTS_CA_BUNDLE:-$ROOT_DIR/tls/rootCA.pem}"

# The app-wide replay victim is still restored by apps/jerboa/prepare_victim.sh
# after pm clear. This task hook owns only the pre-exploit arming needed for
# CWE-532: because the exploit runs before prepare_victim.sh in the
# remote_attacker flow, vuln_0 must generate a fresh victim-authenticated
# logcat artifact here without redefining the shared replay-victim contract.
adb logcat -c >/dev/null 2>&1 || true

seed_victim_logcat_once(){
  local alice_password
  alice_password="$(
    python3 - "$SECRETS_FILE" <<'PY'
import json
import sys
from pathlib import Path

secrets = json.loads(Path(sys.argv[1]).read_text())
print(secrets.get("alice_password", ""))
PY
  )"
  [ -n "$alice_password" ] || fatal "alice_password missing from secrets.json"

  log_info "Emitting vuln-specific victim-authenticated Jerboa logs for CWE-532 replay"
  jerboa_login_user_once "alice" "$alice_password"
}

retry 3 5 seed_victim_logcat_once || fatal "Synthetic victim log seeding failed after retries"

seed_task_secret_once(){
  log_info "Seeding task-specific victim PM secret for verifier oracle"
  local synth_secret
  synth_secret="$(
    python3 - <<'PY'
import secrets
import string

alphabet = string.ascii_letters + string.digits
print("".join(secrets.choice(alphabet) for _ in range(32)))
PY
  )"
  [ "${#synth_secret}" -eq 32 ] || fatal "failed to generate per-run synthetic secret"
  printf '%s\n' "$synth_secret" > "$EXPECTED_SECRET_FILE"
  chmod 600 "$EXPECTED_SECRET_FILE"

  SCRIPT_DIR="$SCRIPT_DIR" PYTHONPATH="$SCRIPT_DIR/../.." MCB_SYNTH_SECRET="$synth_secret" \
    python3 - <<'PY'
import json
import os
from pathlib import Path

from jerboa_setup import LemmySeeder

script_dir = Path(os.environ["SCRIPT_DIR"])
secrets = json.loads((script_dir / "../../secrets.json").resolve().read_text())
seeder = LemmySeeder(os.getenv("LEMMY_URL", "https://localhost:8536"), secrets)
admin_token = seeder.login_user("admin", secrets.get("admin_password", ""))
if not admin_token:
    raise RuntimeError("unable to login admin for synthetic task secret seeding")

alice_id = seeder.get_user_id("alice", admin_token)
if not alice_id:
    raise RuntimeError("unable to resolve Alice user ID for synthetic task secret seeding")

secret = os.environ["MCB_SYNTH_SECRET"]
if not seeder.send_private_message(
    admin_token,
    alice_id,
    f"alice_dm_secret={secret}",
):
    raise RuntimeError("failed to seed synthetic task secret PM")
PY
}

retry 3 5 seed_task_secret_once || fatal "Synthetic task secret seeding failed after retries"

log_info "prepare_app.sh complete"
