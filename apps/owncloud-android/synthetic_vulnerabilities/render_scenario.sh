#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "$0")" && pwd)"
CODEGEN="${CODEGEN:-$SCRIPT_DIR/attacker_code_gen.sh}"
TEMPLATE="${TEMPLATE:-$SCRIPT_DIR/scenario.json}"
OUTPUT="${OUTPUT:-$TEMPLATE}"

log(){ printf '[render-scenario] %s\n' "$*"; }
fail(){ printf '[render-scenario][error] %s\n' "$*" >&2; exit 1; }

[ -x "$CODEGEN" ] || fail "code generator not found: $CODEGEN"
[ -f "$TEMPLATE" ] || fail "template not found: $TEMPLATE"

code=$("$CODEGEN" | awk '/Authorization code:/ {print $NF; exit}')
[ -n "$code" ] || fail "authorization code not found"

python - "$TEMPLATE" "$OUTPUT" "$code" <<'PY' || fail "render failed"
import json, sys
tpl_path, out_path, code = sys.argv[1:4]
with open(tpl_path, "r", encoding="utf-8") as f:
    data = json.load(f)
data["seeded_identities"]["attacker_authorization_code"] = code
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
PY

log "Wrote $OUTPUT with code $code"
