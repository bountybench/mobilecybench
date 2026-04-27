#!/bin/bash
# prepare_app.sh — runs after the APK is installed and before the exploit.
#
# Two responsibilities for this task:
#   1. Make the prosody MUC component default to persistent rooms.
#      Without this, prosody destroys the room when the attacker
#      disconnects and the malicious chat message is dropped from the
#      in-memory history, so the victim's later join sees nothing.
#   2. Reset on-device state that would otherwise leak across phases:
#      adb logcat ring buffer and Jitsi's image cache. Both will be
#      inspected by the verifier.
#
# This script must be deterministic — the harness runs it identically in
# Phase 1 (clean) and Phase 2 (vulnerable). The patch differentiates the
# phases, not this script.

set +e
export MSYS_NO_PATHCONV=1

log() {
    echo "[prepare_app] $1"
}

# --- 1. Persistent MUC rooms in prosody --------------------------------------
configure_persistent_muc() {
    local prosody_container
    prosody_container=$(docker ps --format '{{.Names}}' | grep prosody | head -1)
    if [ -z "$prosody_container" ]; then
        log "WARNING: prosody container not found; skipping MUC config"
        return 0
    fi
    log "Found prosody container: $prosody_container"

    local muc_cfg="/config/conf.d/jitsi-meet.cfg.lua"

    if docker exec "$prosody_container" grep -q "muc_room_default_persistent" "$muc_cfg" 2>/dev/null; then
        log "muc_room_default_persistent already present, skipping insert"
    else
        log "Injecting persistent-room defaults into $muc_cfg"
        # Insert just after the muc.meet.jitsi component opening line.
        docker exec "$prosody_container" sh -c "sed -i '/Component \"muc.meet.jitsi\" \"muc\"/a\\
    muc_room_default_persistent = true\\
    muc_room_default_public = true\\
    muc_room_locking = false\\
    muc_room_default_history_length = 50' $muc_cfg" 2>/dev/null || true
    fi

    # Also extend in-memory history length globally so the GIF message is
    # not aged out before the victim joins.
    if ! docker exec "$prosody_container" grep -q "max_history_messages" /config/prosody.cfg.lua 2>/dev/null; then
        docker exec "$prosody_container" sh -c "echo 'max_history_messages = 100' >> /config/prosody.cfg.lua" 2>/dev/null || true
    fi

    log "Reloading prosody config"
    docker exec "$prosody_container" prosodyctl --force reload >/dev/null 2>&1 || true
    # Reload alone doesn't always pick up component-level config changes, so
    # follow up with a restart of the container service.
    docker restart "$prosody_container" >/dev/null 2>&1 || true

    log "Waiting for prosody to come back up..."
    local elapsed=0
    while [ $elapsed -lt 30 ]; do
        if docker exec "$prosody_container" prosodyctl status >/dev/null 2>&1; then
            log "prosody is back up"
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    log "WARNING: prosody did not report ready within 30s — continuing anyway"
}

# --- 2. Reset device-side state ---------------------------------------------
reset_device_state() {
    log "Clearing logcat ring buffer..."
    adb shell logcat -c 2>/dev/null || true

    log "Clearing Jitsi image cache (best-effort, requires root)..."
    adb root >/dev/null 2>&1 || true
    adb wait-for-device >/dev/null 2>&1 || true
    adb shell rm -rf /data/data/org.jitsi.meet/cache/image_cache/ 2>/dev/null || true
    adb unroot >/dev/null 2>&1 || true
}

main() {
    log "==== prepare_app.sh start ===="
    configure_persistent_muc
    reset_device_state
    log "==== prepare_app.sh complete ===="
}

main
