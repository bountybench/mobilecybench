#!/bin/bash
# reemit_logcat_fence.sh — re-write the verifier-owned logcat fence marker.
#
# capture_verifier_baseline.py (called from start_runtime.sh) writes a unique
# UUID-tagged marker into adb logcat and saves it to
# verifier_artifacts/baseline_meta.json. Probes use that marker to bound
# "post-baseline" log lines (test_access_control.py:post_baseline_log_lines,
# test_integrity.py likewise). Any subsequent `adb logcat -c` clears the
# marker out of the ring buffer, so the fence-backed checks degrade to
# InfraError. This helper re-emits the *same* marker from the saved
# baseline_meta.json so phase isolation is preserved while the fence stays
# locatable in current logcat.
#
# Idempotent. Safe to call multiple times. Exits 0 even if the marker cannot
# be re-emitted; downstream probes will SKIP if the fence is missing.

set +e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
META_FILE="${MCB_BASELINE_META:-$SCRIPT_DIR/verifier_artifacts/baseline_meta.json}"

log() {
    echo "[reemit_logcat_fence] $*"
}

if ! command -v adb >/dev/null 2>&1; then
    log "WARNING: adb not on PATH; cannot re-emit fence"
    exit 0
fi

if ! adb get-state >/dev/null 2>&1; then
    log "WARNING: no adb device; cannot re-emit fence"
    exit 0
fi

if [ ! -f "$META_FILE" ]; then
    log "WARNING: $META_FILE not present; fence-backed probes will SKIP"
    exit 0
fi

fence_tag=$(python3 - "$META_FILE" <<'PY' 2>/dev/null
import json, sys
try:
    print(json.load(open(sys.argv[1])).get("logcat_fence_tag", ""))
except Exception:
    pass
PY
)
fence_marker=$(python3 - "$META_FILE" <<'PY' 2>/dev/null
import json, sys
try:
    print(json.load(open(sys.argv[1])).get("logcat_fence_marker", ""))
except Exception:
    pass
PY
)

if [ -z "$fence_tag" ] || [ -z "$fence_marker" ]; then
    log "WARNING: $META_FILE missing logcat_fence_tag/marker; fence-backed probes will SKIP"
    exit 0
fi

log "Re-emitting verifier fence tag=$fence_tag marker=$fence_marker"
if ! adb shell log -t "$fence_tag" "$fence_marker" >/dev/null 2>&1; then
    if ! adb shell toybox log -t "$fence_tag" "$fence_marker" >/dev/null 2>&1; then
        log "WARNING: failed to re-emit fence marker; fence-backed probes may SKIP"
    fi
fi

exit 0
