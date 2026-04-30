#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
source "$ROOT_DIR/utils/android.sh"

SECRETS_FILE="$SCRIPT_DIR/../../secrets.json"
LOGIN_SCRIPT="$SCRIPT_DIR/exploit_files/login_automation.py"
METADATA_FILE="$SCRIPT_DIR/../../metadata.json"

log_info "Preparing Jerboa synthetic vuln-0 victim state"

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
[ -f "$LOGIN_SCRIPT" ] || fatal "login_automation.py not found"
[ -f "$METADATA_FILE" ] || fatal "metadata.json not found"

alice_password="$(
  python3 - "$SECRETS_FILE" <<'PY'
import json
import sys
from pathlib import Path

secrets = json.loads(Path(sys.argv[1]).read_text())
print(secrets["alice_password"])
PY
)"
[ -n "$alice_password" ] || fatal "alice_password missing from secrets.json"

export REQUESTS_CA_BUNDLE="${REQUESTS_CA_BUNDLE:-$ROOT_DIR/tls/rootCA.pem}"

login_alice_once(){
  log_info "Logging Alice in for the CWE-532 logcat leak scenario"
  local emulator_server
  emulator_server="${JERBOA_INSTANCE_URL:-$(
    python3 - "$METADATA_FILE" <<'PY'
import json
import sys
from pathlib import Path

metadata = json.loads(Path(sys.argv[1]).read_text())
print(metadata["emulator_server"])
PY
  )}"
  [ -n "$emulator_server" ] || fatal "emulator server missing from metadata.json"

  PYTHONPATH="$ROOT_DIR" python3 "$LOGIN_SCRIPT" \
    "$emulator_server" "alice" "$alice_password"
}

retry 3 5 login_alice_once || fatal "Alice login failed after retries"

log_info "prepare_app.sh complete"
