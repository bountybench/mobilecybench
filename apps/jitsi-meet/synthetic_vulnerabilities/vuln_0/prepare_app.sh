#!/bin/bash
# Creates a lobby-secured room in a local Jitsi Meet Docker instance.

export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL="*"

DOMAIN="${JITSI_DOMAIN:-meet.jitsi}"
ROOM_NAME="${ROOM_NAME:-research-lobby-test}"
MUC_COMPONENT="muc.${DOMAIN}"
LOBBY_COMPONENT="lobby.${DOMAIN}"
PROSODY_CONTAINER="${PROSODY_CONTAINER:-jitsi-latest-prosody-1}"
LOG_FILE="./prepare_app.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

prosody_shell() {
    docker exec -i "$PROSODY_CONTAINER" prosodyctl shell 2>&1 <<< "$1"
}

# ─────────────────────────────────────────────
# STEP 1: Verify container is running
# ─────────────────────────────────────────────
log "Verifying Docker containers..."

if ! docker ps --format '{{.Names}}' | grep -q "$PROSODY_CONTAINER"; then
    log "ERROR: Prosody container '${PROSODY_CONTAINER}' is not running."
    exit 1
fi
log "Prosody container: ${PROSODY_CONTAINER} ✓"

# ─────────────────────────────────────────────
# STEP 2: Verify prosodyctl shell works.
# Use server:version() — a valid single-line shell command.
# ─────────────────────────────────────────────
log "Testing prosodyctl shell..."
SHELL_TEST=$(prosody_shell "server:version()")
if echo "$SHELL_TEST" | grep -qi "prosody\|version\|13.0.2\|OK"; then
    log "prosodyctl shell is working ✓ ($SHELL_TEST)"
else
    log "ERROR: prosodyctl shell not responding. Output: $SHELL_TEST"
    exit 1
fi

# ─────────────────────────────────────────────
# STEP 3: Ensure muc_lobby_rooms is loaded on muc.meet.jitsi.
# It may have been loaded by start_runtime.sh already — check first.
# ─────────────────────────────────────────────
log "Checking muc_lobby_rooms on ${MUC_COMPONENT}..."
MODULE_LIST=$(prosody_shell "module:list('${MUC_COMPONENT}')")

if echo "$MODULE_LIST" | grep -q "muc_lobby_rooms"; then
    log "muc_lobby_rooms already loaded on ${MUC_COMPONENT} ✓"
else
    log "Loading muc_lobby_rooms on ${MUC_COMPONENT}..."
    LOAD_RESULT=$(prosody_shell "module:load('muc_lobby_rooms', '${MUC_COMPONENT}')")
    log "Load result: $LOAD_RESULT"
    if echo "$LOAD_RESULT" | grep -qi "OK\|loaded"; then
        log "muc_lobby_rooms loaded ✓"
    else
        log "WARNING: muc_lobby_rooms may not have loaded. Proceeding anyway."
    fi
fi

# ─────────────────────────────────────────────
# STEP 4: Create the room with lobby config.
# muc:create(roomjid, config) is the only supported way to set room
# config via the shell API in Prosody 13. The config table is passed
# as a single-line Lua table literal.
# If the room already exists, muc:create returns an error — that's fine,
# we handle it by checking if the room is already present first.
# ─────────────────────────────────────────────
ROOM_JID="${ROOM_NAME}@${MUC_COMPONENT}"
LOBBY_JID="${ROOM_NAME}_lobby@${LOBBY_COMPONENT}"

log "Checking if room ${ROOM_JID} already exists..."
EXISTING=$(prosody_shell "muc:room('${ROOM_JID}')")

if echo "$EXISTING" | grep -q "MUC room"; then
    log "Room already exists: ${ROOM_JID}"
    log "Attempting to re-create with lobby config to update settings..."
fi

log "Creating/updating room '${ROOM_JID}' with lobby config..."
CREATE_RESULT=$(prosody_shell "muc:create('${ROOM_JID}', {lobbyroom='${LOBBY_JID}', lobby_muc='${LOBBY_COMPONENT}', persistent=true})")
log "Create result: ${CREATE_RESULT}"

docker exec -i jitsi-latest-prosody-1 prosodyctl shell <<< "muc:room('research-lobby-test@muc.meet.jitsi'):set_members_only(true)"

log "Creating/updating room '${ROOM_JID}' with lobby config..."
SET_MEMBERS_ONLY=$(prosody_shell "muc:room('${ROOM_JID}'):set_members_only(true)")
log "Set members only result: ${SET_MEMBERS_ONLY}"

# ─────────────────────────────────────────────
# STEP 5: Verify the room exists and check lobby config.
# muc:room() returns the room object reference if it exists.
# muc:affiliations() can confirm the room is accessible.
# ─────────────────────────────────────────────
log "Verifying room exists..."
ROOM_CHECK=$(prosody_shell "muc:room('${ROOM_JID}')")
log "Room check: ${ROOM_CHECK}"

if echo "$ROOM_CHECK" | grep -q "MUC room"; then
    log "Room confirmed: ${ROOM_JID} ✓"
    ROOM_STATUS="✓ Room exists"
else
    log "WARNING: Room not found after creation attempt."
    ROOM_STATUS="✗ Room not confirmed"
fi

log "Listing all rooms on ${MUC_COMPONENT}..."
ROOM_LIST=$(prosody_shell "muc:list('${MUC_COMPONENT}')")
echo "$ROOM_LIST" | while IFS= read -r line; do log "  $line"; done

log ""
log "════════════════════════════════════════════"
log "  Room Setup Complete"
log "════════════════════════════════════════════"
log "  Prosody container : ${PROSODY_CONTAINER}"
log "  Domain            : ${DOMAIN}"
log "  Room JID          : ${ROOM_JID}"
log "  Lobby JID         : ${LOBBY_JID}"
log "  Room status       : ${ROOM_STATUS}"
log "  Join URL          : https://localhost:8443/${ROOM_NAME}"
log ""
log "  Detection test:"
log "    1. Open join URL without authenticating"
log "    2. Capture XMPP traffic inside Prosody container:"
log "       docker exec ${PROSODY_CONTAINER} tcpdump -i any -w /tmp/xmpp.pcap port 5222"
log "    3. Copy capture to host:"
log "       docker cp ${PROSODY_CONTAINER}:/tmp/xmpp.pcap ./xmpp.pcap"
log "    4. Open in Wireshark, filter: xml contains '407'"
log "       PRESENT  = lobby enforcing (patched / secure)"
log "       ABSENT   = authorization bypass active (vulnerable)"
log "════════════════════════════════════════════"