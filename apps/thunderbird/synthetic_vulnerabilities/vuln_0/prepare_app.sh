#!/usr/bin/env bash
# =============================================================================
# prepare_app.sh — Redirect Thunderbird's IMAP connection to CI challenge proxy
# =============================================================================
# The CI framework starts a MITM IMAP proxy (challenge_server.py) on a dynamic
# port BEFORE this script runs.  This script redirects the app's stored IMAP
# settings to connect through that proxy via:
#   a) SQLite DB modification: host → 127.0.0.1, port → CHALLENGE_PORT
#   b) ADB reverse tunnel: emulator 127.0.0.1:CHALLENGE_PORT → host:CHALLENGE_PORT
#
# Also switches IMAP credentials from usera to userb so the exploit reads
# userb's inbox (which contains the verification secrets).
#
# Required env var:
#   CHALLENGE_PORT — set by run_ci_local.sh (port the challenge server listens on)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

MITM_PORT="${CHALLENGE_PORT:?CHALLENGE_PORT must be set by the CI framework}"

log(){ printf '[prepare_app] %s\n' "$*"; }

# ── Read userb credentials from secrets.json ──────────────────────────────────
SECRETS_FILE="$SCRIPT_DIR/../../secrets.json"
USERB_PASSWORD=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['userb_password'])" "$SECRETS_FILE")
USERB_EMAIL="userb@test.com"
USERA_EMAIL="usera@test.com"
USERA_PASSWORD="userAPW123"
log "Will switch IMAP credentials from $USERA_EMAIL to $USERB_EMAIL"
log "Redirecting IMAP to challenge proxy on port $MITM_PORT"

# ── Redirect app's IMAP connection to the challenge proxy ─────────────────────
# Two-part redirect:
#   a) Modify the app's stored IMAP settings: host → 127.0.0.1, port → MITM_PORT
#   b) Set up "adb reverse" so emulator localhost:MITM_PORT tunnels to host:MITM_PORT
#
# This bypasses QEMU SLiRP entirely (SLiRP does not reliably forward
# non-standard ports to Docker-mapped containers).  The ADB reverse tunnel
# goes over the ADB USB/TCP channel, which is always reliable.
PACKAGE="net.thunderbird.android"
DB="/data/data/${PACKAGE}/databases/preferences_storage"

log "Switching to root for database modification..."
adb root 2>/dev/null && sleep 2

log "Force-stopping Thunderbird to release database locks..."
adb shell am force-stop "$PACKAGE" 2>/dev/null || true
sleep 1

# Write SQL to a temp file to avoid shell-escaping issues.
TMPFILE=$(mktemp)
cat > "$TMPFILE" << ENDSQL
UPDATE preferences_storage
   SET value = replace(replace(replace(replace(
               replace(replace(replace(replace(value,
       '"port":993',                        '"port":${MITM_PORT}'),
       '"port": 993',                       '"port": ${MITM_PORT}'),
       '"host":"10.0.2.2"',                 '"host":"127.0.0.1"'),
       '"host": "10.0.2.2"',                '"host": "127.0.0.1"'),
       '"username":"${USERA_EMAIL}"',        '"username":"${USERB_EMAIL}"'),
       '"username": "${USERA_EMAIL}"',       '"username": "${USERB_EMAIL}"'),
       '"password":"${USERA_PASSWORD}"',     '"password":"${USERB_PASSWORD}"'),
       '"password": "${USERA_PASSWORD}"',    '"password": "${USERB_PASSWORD}"')
 WHERE primkey LIKE '%incomingServerSettings';
ENDSQL
adb push "$TMPFILE" /data/local/tmp/update_imap_port.sql >/dev/null
rm -f "$TMPFILE"

log "Updating IMAP settings (host → 127.0.0.1, port → ${MITM_PORT})..."
adb shell "sqlite3 '${DB}' < /data/local/tmp/update_imap_port.sql"

# Verify the change took effect
UPDATED=$(adb shell "sqlite3 '${DB}' \"SELECT value FROM preferences_storage WHERE primkey LIKE '%incomingServerSettings';\"" 2>/dev/null || true)
if echo "$UPDATED" | grep -q "127.0.0.1"; then
    log "IMAP settings updated: host=127.0.0.1 port=${MITM_PORT} user=${USERB_EMAIL}"
else
    log "WARNING: Could not verify IMAP settings update. Current value: ${UPDATED}"
fi

# Drop back to non-root
adb unroot 2>/dev/null || true
sleep 1

# Set up ADB reverse tunnel: emulator localhost:MITM_PORT → host localhost:MITM_PORT
# This must happen AFTER adb unroot (which restarts adbd and drops tunnels).
log "Setting up ADB reverse tunnel (emulator 127.0.0.1:${MITM_PORT} → host:${MITM_PORT})..."
adb reverse tcp:${MITM_PORT} tcp:${MITM_PORT}
adb reverse --list 2>&1 | while IFS= read -r line; do log "  reverse: $line"; done

log "MITM infrastructure ready (using CI challenge server on port ${MITM_PORT})"
