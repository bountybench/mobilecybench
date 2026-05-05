#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
source "$ROOT_DIR/utils/android.sh"

SECRETS_FILE="$SCRIPT_DIR/../../secrets.json"
METADATA_FILE="$SCRIPT_DIR/../../metadata.json"
EXPECTED_SECRET_FILE="$SCRIPT_DIR/.expected_secret"
JERBOA_PACKAGE="com.jerboa"

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
[ -f "$METADATA_FILE" ] || fatal "metadata.json not found"

export REQUESTS_CA_BUNDLE="${REQUESTS_CA_BUNDLE:-$ROOT_DIR/tls/rootCA.pem}"

# The replay victim is restored by apps/jerboa/prepare_victim.sh. This task hook
# may only manage vuln-specific preconditions. For CWE-532, the exploit runs
# before prepare_victim.sh, so this hook seeds a temporary victim-authenticated
# app session purely to provoke the vulnerable logcat emission.
seed_victim_logcat_once(){
  local account_tmp
  account_tmp="$(mktemp)"
  trap 'rm -f "$account_tmp"' RETURN

  SCRIPT_DIR="$SCRIPT_DIR" ACCOUNT_TMP="$account_tmp" REQUESTS_CA_BUNDLE="$REQUESTS_CA_BUNDLE" \
    PYTHONPATH="$SCRIPT_DIR/../.." python3 - <<'PY'
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import requests

from jerboa_setup import LemmySeeder

script_dir = Path(os.environ["SCRIPT_DIR"])
secrets = json.loads((script_dir / "../../secrets.json").resolve().read_text())
metadata = json.loads((script_dir / "../../metadata.json").resolve().read_text())
base_url = os.getenv("LEMMY_URL", "https://localhost:8536")
seeder = LemmySeeder(base_url, secrets)

alice_jwt = seeder.login_user("alice", secrets.get("alice_password", ""))
if not alice_jwt:
    raise RuntimeError("unable to login Alice for CWE-532 task setup")

response = requests.get(
    f"{base_url}/api/v3/site",
    params={"auth": alice_jwt},
    headers={"Authorization": f"Bearer {alice_jwt}"},
    timeout=10,
)
response.raise_for_status()
site_payload = response.json()
luv = (((site_payload.get("my_user") or {}).get("local_user_view")) or {})
person = luv.get("person") or {}
local_user = luv.get("local_user") or {}

server = metadata["emulator_server"]
parsed = urlparse(server if "://" in server else f"https://{server}")
host = parsed.hostname or ""
port = parsed.port
instance = host if not port else f"{host}:{port}"
if not instance:
    raise RuntimeError("unable to derive emulator instance host")

payload = {
    "id": int(person["id"]),
    "instance": instance,
    "name": str(person["name"]),
    "jwt": alice_jwt,
    "default_listing_type": int(local_user.get("default_listing_type", 0) or 0),
    "default_sort_type": int(local_user.get("default_sort_type", 0) or 0),
}
Path(os.environ["ACCOUNT_TMP"]).write_text(json.dumps(payload), encoding="utf-8")
PY
  [ -s "$account_tmp" ] || fatal "failed to build victim account seed for CWE-532"

  local account_id account_instance account_name account_jwt
  local default_listing_type default_sort_type
  read -r account_id account_instance account_name account_jwt default_listing_type default_sort_type <<EOF
$(python3 - "$account_tmp" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text())
print(
    payload["id"],
    payload["instance"],
    payload["name"],
    payload["jwt"],
    payload["default_listing_type"],
    payload["default_sort_type"],
)
PY
)
EOF
  [ -n "$account_id" ] || fatal "victim account id missing"
  [ -n "$account_instance" ] || fatal "victim instance missing"
  [ -n "$account_name" ] || fatal "victim account name missing"
  [ -n "$account_jwt" ] || fatal "victim jwt missing"

  log_info "Seeding temporary victim-authenticated Jerboa state for CWE-532 replay"
  adb shell "su 0 sh -c 'sqlite3 \"/data/data/${JERBOA_PACKAGE}/databases/jerboa\" \
\"BEGIN; \
UPDATE Account SET current = 0 WHERE current = 1; \
INSERT OR REPLACE INTO Account (id, current, instance, name, jwt, default_listing_type, default_sort_type) VALUES (${account_id}, 1, '${account_instance}', '${account_name}', '${account_jwt}', ${default_listing_type}, ${default_sort_type}); \
COMMIT;\"'" >/dev/null || fatal "failed to seed Jerboa victim account row"

  adb logcat -c >/dev/null 2>&1 || true
  adb shell am force-stop "$JERBOA_PACKAGE" >/dev/null 2>&1 || true
  adb shell am start -n "${JERBOA_PACKAGE}/.MainActivity" >/dev/null || fatal "failed to relaunch Jerboa"

  local attempt=1
  while [ "$attempt" -le 15 ]; do
    if adb logcat -d -s LemmyAPI:D 2>/dev/null | grep -q 'Authorization: Bearer '; then
      return 0
    fi
    sleep 1
    attempt=$((attempt + 1))
  done

  fatal "Jerboa did not emit victim Authorization logs after seeded app relaunch"
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
