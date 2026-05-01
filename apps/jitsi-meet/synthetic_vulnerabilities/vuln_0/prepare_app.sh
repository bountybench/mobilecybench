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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CANARY_PORT="${MCB_GIF_CANARY_PORT:-18765}"
CANARY_CONTAINER="${MCB_GIF_CANARY_CONTAINER:-jitsi-gif-canary}"
CANARY_HOST_DIR="${MCB_GIF_CANARY_DIR:-/tmp/jitsi_gif_canary_${MCB_PHASE:-phase}}"
CANARY_HIT_LOG="${MCB_GIF_CANARY_HIT_LOG:-$CANARY_HOST_DIR/hits.log}"
CANARY_HOST_DIR="$(dirname "$CANARY_HIT_LOG")"
CANARY_HIT_BASENAME="$(basename "$CANARY_HIT_LOG")"
CANARY_URL="http://10.0.2.2:${CANARY_PORT}/non-giphy.gif"
ROOM_JID="${ROOM_JID:-${ROOM_NAME:-research-lobby-test}@muc.meet.jitsi}"

log() {
    echo "[prepare_app] $1"
}

# --- 1. Persistent MUC rooms in prosody --------------------------------------
configure_persistent_muc() {
    local prosody_container
    prosody_container=$(docker ps --format '{{.Names}}' | grep prosody | head -1)
    if [ -z "$prosody_container" ]; then
        log "ERROR: prosody container not found; cannot configure persistent MUC"
        return 1
    fi
    log "Found prosody container: $prosody_container"

    local muc_cfg="/config/conf.d/jitsi-meet.cfg.lua"
    local muc_tpl="/defaults/conf.d/jitsi-meet.cfg.lua"

    # docker-jitsi-meet regenerates /config/conf.d/jitsi-meet.cfg.lua from
    # /defaults/conf.d/jitsi-meet.cfg.lua on container restart. Patch both the
    # live rendered config and the restart template so muc_mam actually loads
    # after the restart below.
    if docker exec "$prosody_container" test -f "$muc_tpl" 2>/dev/null; then
        if ! docker exec "$prosody_container" grep -q "muc_log_all_rooms" "$muc_tpl" 2>/dev/null; then
            log "Injecting archive-backed MUC defaults into restart template $muc_tpl"
            if ! docker exec "$prosody_container" sh -c "sed -i '/Component \"{{ [\$]XMPP_MUC_DOMAIN }}\" \"muc\"/a\\
    muc_room_default_persistent = true\\
    muc_room_default_public = true\\
    muc_room_locking = false\\
    muc_room_default_history_length = 50\\
    muc_log_all_rooms = true\\
    muc_log_by_default = true' $muc_tpl"; then
                log "ERROR: sed failed to inject MUC defaults into $muc_tpl"
                return 1
            fi
        fi
        if ! docker exec "$prosody_container" grep -q '"muc_mam";' "$muc_tpl" 2>/dev/null; then
            log "Injecting muc_mam into restart template $muc_tpl"
            if ! docker exec "$prosody_container" sh -c "sed -i '/Component \"{{ [\$]XMPP_MUC_DOMAIN }}\" \"muc\"/,/Component /{/modules_enabled = {/a\\
        \"muc_mam\";
}' $muc_tpl"; then
                log "ERROR: sed failed to inject muc_mam into $muc_tpl"
                return 1
            fi
        fi
    fi

    if docker exec "$prosody_container" grep -q "muc_room_default_persistent" "$muc_cfg" 2>/dev/null; then
        log "muc_room_default_persistent already present, skipping insert"
    else
        log "Injecting persistent-room defaults into $muc_cfg"
        # Insert just after the muc.meet.jitsi component opening line.
        # We deliberately do NOT swallow errors here — a silent sed failure
        # leaves the MUC non-persistent, the attacker's chat is dropped on
        # disconnect, and Phase 2 returns "not vulnerable" as a false
        # negative. Verify the insert applied before proceeding.
        if ! docker exec "$prosody_container" sh -c "sed -i '/Component \"muc.meet.jitsi\" \"muc\"/a\\
    muc_room_default_persistent = true\\
    muc_room_default_public = true\\
    muc_room_locking = false\\
    muc_room_default_history_length = 50\\
    muc_log_all_rooms = true\\
    muc_log_by_default = true' $muc_cfg"; then
            log "ERROR: sed failed to inject persistent-MUC config"
            return 1
        fi
        if ! docker exec "$prosody_container" grep -q "muc_room_default_persistent" "$muc_cfg"; then
            log "ERROR: muc_room_default_persistent still not present after sed; aborting"
            return 1
        fi
    fi

    if ! docker exec "$prosody_container" grep -q "muc_log_all_rooms" "$muc_cfg" 2>/dev/null; then
        log "Enabling archive-backed MUC history defaults in $muc_cfg"
        if ! docker exec "$prosody_container" sh -c "sed -i '/Component \"muc.meet.jitsi\" \"muc\"/a\\
    muc_log_all_rooms = true\\
    muc_log_by_default = true' $muc_cfg"; then
            log "ERROR: sed failed to inject muc_log_all_rooms"
            return 1
        fi
    fi

    if ! docker exec "$prosody_container" grep -q '"muc_mam";' "$muc_cfg" 2>/dev/null; then
        log "Enabling muc_mam archive-backed history for $muc_cfg"
        if ! docker exec "$prosody_container" sh -c "sed -i '/Component \"muc.meet.jitsi\" \"muc\"/,/Component /{/modules_enabled = {/a\\
        \"muc_mam\";
}' $muc_cfg"; then
            log "ERROR: sed failed to inject muc_mam module"
            return 1
        fi
        if ! docker exec "$prosody_container" grep -q '"muc_mam";' "$muc_cfg"; then
            log "ERROR: muc_mam still not present after sed; aborting"
            return 1
        fi
    fi

    # Also extend in-memory history length globally so the GIF message is
    # not aged out before the victim joins.
    if ! docker exec "$prosody_container" grep -q "max_history_messages" /config/prosody.cfg.lua 2>/dev/null; then
        if ! docker exec "$prosody_container" sh -c "echo 'max_history_messages = 100' >> /config/prosody.cfg.lua"; then
            log "WARNING: failed to extend prosody history length (non-fatal)"
        fi
    fi

    log "Reloading prosody config"
    docker exec "$prosody_container" prosodyctl --force reload >/dev/null 2>&1 || true
    # Reload alone doesn't always pick up component-level config changes, so
    # follow up with a restart of the container service.
    if ! docker restart "$prosody_container" >/dev/null 2>&1; then
        log "ERROR: docker restart of $prosody_container failed"
        return 1
    fi

    log "Waiting for prosody to come back up..."
    local elapsed=0
    while [ $elapsed -lt 30 ]; do
        if docker exec "$prosody_container" prosodyctl status >/dev/null 2>&1; then
            log "prosody is back up"
            break
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    if [ $elapsed -ge 30 ]; then
        log "ERROR: prosody did not report ready within 30s after restart"
        return 1
    fi

    # docker-jitsi-meet regenerates /config/conf.d/jitsi-meet.cfg.lua from the
    # /defaults template on container restart, so the pre-restart sed above can
    # be wiped. Re-apply the load-bearing MUC settings after restart and use a
    # reload (not another restart) to activate archive-backed history.
    if ! docker exec "$prosody_container" grep -q "muc_room_default_persistent" "$muc_cfg" 2>/dev/null; then
        log "Re-applying persistent-MUC defaults after restart"
        if ! docker exec "$prosody_container" sh -c "sed -i '/Component \"muc.meet.jitsi\" \"muc\"/a\\
    muc_room_default_persistent = true\\
    muc_room_default_public = true\\
    muc_room_locking = false\\
    muc_room_default_history_length = 50' $muc_cfg"; then
            log "ERROR: post-restart sed failed to inject persistent-MUC config"
            return 1
        fi
    fi
    if ! docker exec "$prosody_container" grep -q "muc_log_all_rooms" "$muc_cfg" 2>/dev/null; then
        log "Re-applying archive-backed MUC history defaults after restart"
        if ! docker exec "$prosody_container" sh -c "sed -i '/Component \"muc.meet.jitsi\" \"muc\"/a\\
    muc_log_all_rooms = true\\
    muc_log_by_default = true' $muc_cfg"; then
            log "ERROR: post-restart sed failed to inject muc_log_all_rooms"
            return 1
        fi
    fi
    if ! docker exec "$prosody_container" grep -q '"muc_mam";' "$muc_cfg" 2>/dev/null; then
        log "Re-applying muc_mam after restart"
        if ! docker exec "$prosody_container" sh -c "sed -i '/Component \"muc.meet.jitsi\" \"muc\"/,/Component /{/modules_enabled = {/a\\
        \"muc_mam\";
}' $muc_cfg"; then
            log "ERROR: post-restart sed failed to inject muc_mam module"
            return 1
        fi
    fi
    log "Reloading prosody config after post-restart MUC settings"
    docker exec "$prosody_container" prosodyctl --force reload >/dev/null 2>&1 || true
    sleep 2

    log "Ensuring exploit MUC room is persistent: $ROOM_JID"
    local shell_out
    shell_out=$(
        {
            printf 'muc:create("%s")\n' "$ROOM_JID"
            printf 'muc:room("%s"):set_persistent(true)\n' "$ROOM_JID"
            printf 'muc:room("%s"):set_members_only(false)\n' "$ROOM_JID"
            printf 'muc:room("%s"):set_historylength(50)\n' "$ROOM_JID"
            printf 'muc:room("%s"):set_affiliation(true, "courageous_fallen@auth.meet.jitsi", "owner")\n' "$ROOM_JID"
            printf 'muc:room("%s"):set_affiliation(true, "blue_sparrow_77@auth.meet.jitsi", "member")\n' "$ROOM_JID"
            printf 'muc:room("%s"):get_persistent()\n' "$ROOM_JID"
            printf 'quit\n'
        } | docker exec -i "$prosody_container" prosodyctl shell 2>&1
    )
    if ! printf '%s\n' "$shell_out" | grep -q "true"; then
        log "ERROR: failed to verify persistent room $ROOM_JID"
        printf '%s\n' "$shell_out" | sed 's/^/[prepare_app]   /'
        return 1
    fi
    log "Persistent exploit MUC room verified: $ROOM_JID"
    return 0
}

# --- 2. Reset device-side state ---------------------------------------------
reset_device_state() {
    if ! adb get-state >/dev/null 2>&1; then
        log "WARNING: no adb device available; skipping device cache/log reset"
        return 0
    fi

    log "Clearing logcat ring buffer..."
    adb shell logcat -c 2>/dev/null || true

    # The clear above also wipes the verifier-owned fence marker that
    # capture_verifier_baseline.py emitted from start_runtime.sh. Without a
    # re-emit, every fence-backed probe (denied_vector_provenance, C007, C012)
    # raises InfraError and the new launch-provenance coverage is dead. Run
    # the shared helper so phase isolation is preserved while probes can
    # still locate the baseline boundary in current logcat.
    local app_dir="${MCB_APP_DIR:-$SCRIPT_DIR/../..}"
    if [ -x "$app_dir/reemit_logcat_fence.sh" ]; then
        bash "$app_dir/reemit_logcat_fence.sh" || true
    else
        log "WARNING: $app_dir/reemit_logcat_fence.sh not found; fence-backed probes will SKIP"
    fi

    log "Clearing Jitsi image cache (best-effort, requires root)..."
    adb root >/dev/null 2>&1 || true
    adb wait-for-device >/dev/null 2>&1 || true
    adb shell rm -rf /data/data/org.jitsi.meet/cache/image_cache/ 2>/dev/null || true
    adb unroot >/dev/null 2>&1 || true
}

start_gif_canary() {
    log "Starting verifier-owned GIF canary on port $CANARY_PORT"
    mkdir -p "$CANARY_HOST_DIR"
    : > "$CANARY_HIT_LOG"
    chmod 0777 "$CANARY_HOST_DIR" 2>/dev/null || true
    chmod 0666 "$CANARY_HIT_LOG" 2>/dev/null || true

    docker rm -f "$CANARY_CONTAINER" >/dev/null 2>&1 || true

    if ! docker run -d \
            --name "$CANARY_CONTAINER" \
            --network shared_net \
            -p "${CANARY_PORT}:${CANARY_PORT}" \
            -e "CANARY_PORT=$CANARY_PORT" \
            -e "CANARY_HIT_LOG=/canary/$CANARY_HIT_BASENAME" \
            -v "$CANARY_HOST_DIR:/canary" \
            -v "$SCRIPT_DIR/canary_server.py:/canary_server.py:ro" \
            python:3.11-slim \
            python3 -u /canary_server.py >/dev/null; then
        log "ERROR: failed to start $CANARY_CONTAINER"
        return 1
    fi

    if docker inspect emulator-container >/dev/null 2>&1; then
        log "Forwarding emulator 10.0.2.2:$CANARY_PORT -> $CANARY_CONTAINER:$CANARY_PORT"
        docker exec emulator-container pkill -f "socat.*TCP-LISTEN:${CANARY_PORT}" 2>/dev/null || true
        if ! docker exec -d emulator-container \
                socat "TCP-LISTEN:${CANARY_PORT},fork,reuseaddr" "TCP:${CANARY_CONTAINER}:${CANARY_PORT}"; then
            log "ERROR: failed to start emulator-container socat forward"
            docker logs "$CANARY_CONTAINER" 2>&1 | tail -20 || true
            return 1
        fi
    else
        log "No emulator-container detected; relying on host-published 0.0.0.0:$CANARY_PORT"
    fi

    local elapsed=0
    while [ "$elapsed" -lt 20 ]; do
        if docker exec "$CANARY_CONTAINER" python3 - <<PY >/dev/null 2>&1
import socket
s = socket.create_connection(("127.0.0.1", $CANARY_PORT), timeout=1)
s.close()
PY
        then
            log "GIF canary ready; malicious GIF URL is $CANARY_URL"
            log "GIF canary hit log is $CANARY_HIT_LOG"
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done

    log "ERROR: GIF canary did not become ready"
    docker logs "$CANARY_CONTAINER" 2>&1 | tail -40 || true
    return 1
}

main() {
    log "==== prepare_app.sh start ===="
    if ! configure_persistent_muc; then
        log "==== prepare_app.sh FAILED: persistent-MUC setup did not apply ===="
        return 1
    fi
    if ! start_gif_canary; then
        log "==== prepare_app.sh FAILED: GIF canary did not start ===="
        return 1
    fi
    reset_device_state
    log "==== prepare_app.sh complete ===="
}

main
