#!/bin/bash
# hydrate_state.sh — app-local wrapper around the final Jitsi hydration plan.
#
# This is the single integration point used by start_runtime.sh and
# prepare_victim.sh.  It keeps the actual implementation in
# apps/jitsi-meet/hydration/setup_state.sh, but supplies the app path/env that the
# helper scripts need and restores normal (non-root) ADB posture afterwards.

set -u
export MSYS_NO_PATHCONV=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HYDRATE_SCRIPT="${MCB_HYDRATE_SCRIPT:-$SCRIPT_DIR/hydration/setup_state.sh}"

log() {
    echo "[hydrate_state] $1"
}

usage() {
    cat <<USAGE
Usage: $0 [full|server|device]

  full    Hydrate device state plus Jitsi/Prosody server context. Standalone
          orchestration only; the harness never invokes this scope.
  server  Hydrate Prosody/MUC/chat-history server-side context only. No
          victim-identity writes to the device. Used by start_runtime.sh —
          for remote_attacker (REDTEAM.md:24-26) the exploit window must
          not see saved credentials/personalization on the device, and the
          harness boundary (pm clear + prepare_victim.sh) is what restores
          victim state for the verifier.
  device  Hydrate Android private app state only (RKStorage, SharedPreferences,
          mcb_private_canary.txt). Used by prepare_victim.sh — the harness
          invokes prepare_victim.sh pre-exploit for malicious_app and post-
          pm-clear for remote_attacker (scripts/task_validation_common.sh:
          367-401), so victim-identity state lands at the AV:N-correct point
          for both models.

Env:
  MCB_SKIP_HYDRATION=1           skip and return success
  MCB_PACKAGE_NAME=<package>     default org.jitsi.meet
  PROSODY_CONTAINER=<name>       default auto-detected prosody container
  MCB_HYDRATION_RESTORE_UNROOT=0 leave adb root posture unchanged
USAGE
}

SCOPE="${1:-${MCB_HYDRATE_SCOPE:-full}}"
case "$SCOPE" in
    full|server|device) ;;
    -h|--help) usage; exit 0 ;;
    *) log "ERROR: unknown hydration scope '$SCOPE'"; usage; exit 2 ;;
esac

if [ "${MCB_SKIP_HYDRATION:-0}" = "1" ]; then
    log "MCB_SKIP_HYDRATION=1; skipping $SCOPE hydration"
    exit 0
fi

if [ ! -f "$HYDRATE_SCRIPT" ]; then
    log "ERROR: hydration script not found: $HYDRATE_SCRIPT"
    exit 1
fi

# Helpers under apps/jitsi-meet/hydration need the app directory to load secrets
# and metadata.  setup_state.sh itself also consumes MCB_PACKAGE_NAME.
export MCB_APP_DIR="${MCB_APP_DIR:-$SCRIPT_DIR}"
export MCB_PACKAGE_NAME="${MCB_PACKAGE_NAME:-org.jitsi.meet}"
export MCB_HYDRATE_SCOPE="$SCOPE"

# Prefer the configured default, but auto-detect when compose generated a
# different prefix.  This is read by setup_state.sh and _prosody_shell.py.
if [ -z "${PROSODY_CONTAINER:-}" ]; then
    detected="$(docker ps --format '{{.Names}}' 2>/dev/null | grep -E '(^|-)prosody(-|$)' | head -1 || true)"
    if [ -n "$detected" ]; then
        export PROSODY_CONTAINER="$detected"
    fi
fi

restore_adb_posture() {
    if [ "${MCB_HYDRATION_RESTORE_UNROOT:-1}" != "1" ]; then
        return 0
    fi
    if command -v adb >/dev/null 2>&1; then
        adb wait-for-device >/dev/null 2>&1 || true
        # adb unroot commonly returns non-zero while adbd restarts; never let
        # cleanup mask the hydration result.
        adb unroot >/dev/null 2>&1 || true
        adb wait-for-device >/dev/null 2>&1 || true
    fi
}
trap restore_adb_posture EXIT

log "Running $SCOPE hydration via $HYDRATE_SCRIPT"
log "MCB_APP_DIR=$MCB_APP_DIR MCB_PACKAGE_NAME=$MCB_PACKAGE_NAME PROSODY_CONTAINER=${PROSODY_CONTAINER:-<default>}"

bash "$HYDRATE_SCRIPT"
