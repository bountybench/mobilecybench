#!/usr/bin/env bash
set -euo pipefail

RUNTIME_MANIFEST="${TMPDIR:-/tmp}/mobilecybench-owntracks-runtime/runtime_manifest.json"
[[ -f "$RUNTIME_MANIFEST" ]] || { echo "missing runtime manifest: $RUNTIME_MANIFEST" >&2; exit 2; }
PKG="$(python3 - "$RUNTIME_MANIFEST" <<'PY'
import json, sys
with open(sys.argv[1], "r", encoding="utf-8") as fh:
    data = json.load(fh)
print(data["package_name"])
PY
)"

adb shell am force-stop "$PKG" >/dev/null 2>&1 || true
