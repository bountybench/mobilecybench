#!/bin/bash
# hydrate_state.sh — app-local wrapper around the final Jitsi hydration plan.
#
# This is the single integration point used by start_runtime.sh and
# prepare_victim.sh.  It keeps the actual implementation in
# hydrate_final/hydration/setup_state.sh, but supplies the app path/env that the
# helper scripts need and restores normal (non-root) ADB posture afterwards.

set -u
export MSYS_NO_PATHCONV=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
HYDRATE_SCRIPT="${MCB_HYDRATE_SCRIPT:-$ROOT_DIR/hydrate_final/hydration/setup_state.sh}"

log() {
    echo "[hydrate_state] $1"
}

usage() {
    cat <<USAGE
Usage: $0 [full|device]

  full    Hydrate device state plus Jitsi/Prosody server context.
  device  Rehydrate only Android private app state after pm clear; do not
          append MUC/chat history or otherwise mutate server state.

Env:
  MCB_SKIP_HYDRATION=1           skip and return success
  MCB_PACKAGE_NAME=<package>     default org.jitsi.meet
  PROSODY_CONTAINER=<name>       default auto-detected prosody container
  MCB_HYDRATION_RESTORE_UNROOT=0 leave adb root posture unchanged
USAGE
}

SCOPE="${1:-${MCB_HYDRATE_SCOPE:-full}}"
case "$SCOPE" in
    full|device) ;;
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

# Helpers under hydrate_final/hydration need the app directory to load secrets
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
