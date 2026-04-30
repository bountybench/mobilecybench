#!/bin/bash
# prepare_victim.sh — invoked by the harness AFTER the exploit runs and
# AFTER pm clear, when attacker_model=remote_attacker. The device is back
# to a freshly-installed state at this point; we have to re-launch Jitsi
# and walk it into whatever the "victim experiences the attack" state is
# for the active task.
#
# For vuln_0 (chat-delivered GIF XSS): the victim's job is to land in the
# in-meeting chat panel of the same MUC room the attacker posted into,
# so prosody's history replay re-arms the vulnerable isGifUrlAllowed
# code path on a fresh client. The verifier then inspects Fresco's
# image cache.
#
# This script must:
#   - Be deterministic (no race-y waits).
#   - Tolerate being invoked with no MCB_TASK_DIR (when called from
#     ad-hoc test harnesses) by falling back to safe defaults.
#   - Re-apply device hydration after pm clear without mutating
#     server-side attacker evidence collected during the exploit phase.

set +e
export MSYS_NO_PATHCONV=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_NAME="${MCB_PACKAGE_NAME:-org.jitsi.meet}"
ROOM_NAME="${ROOM_NAME:-research-lobby-test}"

log() {
    echo "[prepare_victim] $1"
}

# Look up a task-local jitsi_exploit.py (used as a UI-automation library
# in --mode victim). If the task ships one we use it; otherwise the
# function is a no-op and we just open the app.
find_ui_helper() {
    local candidates=(
        "${MCB_TASK_DIR:-}/exploit_files/jitsi_exploit.py"
        "$SCRIPT_DIR/synthetic_vulnerabilities/vuln_0/exploit_files/jitsi_exploit.py"
    )
    local c
    for c in "${candidates[@]}"; do
        if [ -n "$c" ] && [ -f "$c" ]; then
            echo "$c"
            return 0
        fi
    done
    echo ""
}

hydrate_victim_device_state() {
    if [ "${MCB_SKIP_HYDRATION:-0}" = "1" ]; then
        log "MCB_SKIP_HYDRATION=1; skipping victim hydration"
        return 0
    fi

    local hydrator="$SCRIPT_DIR/hydrate_state.sh"
    if [ ! -x "$hydrator" ]; then
        log "ERROR: hydrate_state.sh not found/executable at $hydrator"
        return 1
    fi

    # prepare_victim runs after the remote-attacker harness has done
    # `pm clear`, so Android private state is gone.  Do *device*-scope
    # hydration here: rebuild RKStorage/shared_prefs, but do not append chat
    # history or otherwise mutate Prosody after the exploit has run.
    log "Rehydrating victim Android private state (scope=device)..."
    MCB_APP_DIR="$SCRIPT_DIR" MCB_PACKAGE_NAME="$PACKAGE_NAME" "$hydrator" device
}

main() {
    log "==== prepare_victim.sh start ===="
    log "package=$PACKAGE_NAME room=$ROOM_NAME phase=${MCB_PHASE:-?} attacker_model=${MCB_ATTACKER_MODEL:-?}"

    # Re-grant runtime permissions that pm clear wiped.
    adb shell pm grant "$PACKAGE_NAME" android.permission.CAMERA >/dev/null 2>&1 || true
    adb shell pm grant "$PACKAGE_NAME" android.permission.RECORD_AUDIO >/dev/null 2>&1 || true
    adb shell pm grant "$PACKAGE_NAME" android.permission.POST_NOTIFICATIONS >/dev/null 2>&1 || true
    adb shell appops set "$PACKAGE_NAME" SYSTEM_ALERT_WINDOW allow >/dev/null 2>&1 || true

    if ! hydrate_victim_device_state; then
        log "==== prepare_victim.sh FAILED: victim hydration did not apply ===="
        return 1
    fi

    log "Launching Jitsi (MainActivity)..."
    adb shell am start -n "$PACKAGE_NAME/.MainActivity" >/dev/null 2>&1 || true
    sleep 2

    local helper
    helper="$(find_ui_helper)"
    if [ -z "$helper" ]; then
        log "WARNING: no jitsi_exploit.py UI helper found; victim will only have launched the app"
        log "==== prepare_victim.sh complete (no room join) ===="
        return 0
    fi

    log "Using UI helper: $helper"
    # Bump dwell to 60 s — victim_flow polls the cache and exits as soon
    # as the .cnt appears, so this is a *cap*, not a fixed wait. The
    # legitimate (vulnerable build, post-history-replay) Fresco fetch
    # typically completes inside a few seconds; the cap absorbs slow CI
    # network or animation jank.
    if ! python3 "$helper" \
            --mode victim \
            --room "$ROOM_NAME" \
            --display-name "victim_bob" \
            --dwell-seconds 60; then
        log "WARNING: victim UI flow returned non-zero"
    fi

    log "==== prepare_victim.sh complete ===="
}

main
