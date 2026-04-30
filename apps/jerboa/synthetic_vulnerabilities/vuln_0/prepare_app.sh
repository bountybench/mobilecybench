#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
source "$ROOT_DIR/utils/android.sh"

SECRETS_FILE="$SCRIPT_DIR/../../secrets.json"
LOGIN_SCRIPT="$SCRIPT_DIR/exploit_files/login_automation.py"

log_info "Preparing Jerboa synthetic vuln-0 victim state"

[ -f "$SECRETS_FILE" ] || fatal "secrets.json not found"
[ -f "$LOGIN_SCRIPT" ] || fatal "login_automation.py not found"

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

log_info "Logging Alice in for the CWE-532 logcat leak scenario"
PYTHONPATH="$ROOT_DIR" python3 "$LOGIN_SCRIPT" \
  "${JERBOA_INSTANCE_URL:-https://10.0.2.2:8536}" "alice" "$alice_password" \
  || fatal "Alice login failed"

log_info "prepare_app.sh complete"
