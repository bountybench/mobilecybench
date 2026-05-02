#!/usr/bin/env bash
# Orchestrate full ntfy-android victim-state hydration.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
APP_DIR="${MCB_APP_DIR:-$SCRIPT_DIR}"
PACKAGE="${NTFY_ANDROID_PACKAGE:-io.heckel.ntfy}"
DEVICE_BASE_URL="${EXPECTED_BASE_URL:-http://10.0.2.2:8080}"
SERVER_URL="${NTFY_SERVER_URL:-${NTFY_URL:-http://localhost:8080}}"
TIMEOUT="${HYDRATION_TIMEOUT:-60}"
SKIP_START_RUNTIME="${HYDRATION_SKIP_START_RUNTIME:-0}"
STATE_MANIFEST="${SCRIPT_DIR}/last_state.json"
START_RUNTIME_MANIFEST="${SCRIPT_DIR}/hydration_state.json"

log() { printf '[setup_state] %s\n' "$*" >&2; }
fatal() { printf '[setup_state] ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<USAGE
Usage: apps/ntfy-android/setup_state.sh [start_runtime.sh args]

Runs the existing ntfy-android runtime setup and verifies the hydrated result.
If start_runtime.sh is skipped, this script applies the realistic hydration
overlay itself before verification.

Environment:
  HYDRATION_SKIP_START_RUNTIME=1  Use an already-started fixture instead of
                                  invoking apps/ntfy-android/start_runtime.sh.
  MCB_APP_DIR                     App fixture directory (default apps/ntfy-android).
  NTFY_ANDROID_PACKAGE            Android package (default io.heckel.ntfy).
  EXPECTED_BASE_URL               Device-side base URL (default http://10.0.2.2:8080).
  NTFY_SERVER_URL / NTFY_URL       Host-side server URL (default http://localhost:8080).
  HYDRATION_TIMEOUT               Setup/verification timeout seconds (default 60).
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

command -v python3 >/dev/null 2>&1 || fatal "python3 is required"

if [[ ! -d "$APP_DIR" ]]; then
  fatal "app dir not found: $APP_DIR"
fi
APP_DIR="$(cd "$APP_DIR" && pwd)"

cd "$REPO_ROOT"

if [[ "$SKIP_START_RUNTIME" != "1" ]]; then
  log "running existing ntfy runtime setup ($APP_DIR/start_runtime.sh)"
  "$APP_DIR/start_runtime.sh" "$@"
  if [[ ! -f "$START_RUNTIME_MANIFEST" ]]; then
    fatal "expected hydration manifest missing after start_runtime.sh: $START_RUNTIME_MANIFEST"
  fi
  cp "$START_RUNTIME_MANIFEST" "$STATE_MANIFEST"
  log "reused start_runtime hydration manifest -> $STATE_MANIFEST"
else
  log "HYDRATION_SKIP_START_RUNTIME=1; using existing runtime/app state"
  log "applying realistic victim-state overlay"
  python3 "$SCRIPT_DIR/hydrate_device_state.py" \
    --app-dir "$APP_DIR" \
    --package "$PACKAGE" \
    --base-url "$DEVICE_BASE_URL" \
    --server-url "$SERVER_URL" \
    --timeout "$TIMEOUT" \
    --manifest "$STATE_MANIFEST"
fi

log "verifying hydrated state"
python3 "$SCRIPT_DIR/verify_state.py" \
  --app-dir "$APP_DIR" \
  --package "$PACKAGE" \
  --base-url "$DEVICE_BASE_URL" \
  --server-url "$SERVER_URL" \
  --timeout "$TIMEOUT" \
  --summary "$SCRIPT_DIR/last_verification.json"

log "hydration complete"
log "redacted manifest: $STATE_MANIFEST"
log "verification summary: $SCRIPT_DIR/last_verification.json"
