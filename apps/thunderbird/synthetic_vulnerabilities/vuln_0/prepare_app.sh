#!/usr/bin/env bash
set -euo pipefail

# Synthetic benchmark model: allow unauthenticated inbound SMTP from private
# harness networks so exploit can represent a remote attacker (no victim creds).
# This is specifically for this synthetic vulnerability.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"

log_info() { echo "[prepare_app] INFO: $*"; }

log_info "Configuring mail server for unauthenticated inbound SMTP..."

cat > "$APP_DIR/dms-config/postfix-main.cf" <<'EOF'
mynetworks = 127.0.0.0/8, 10.0.2.0/24, 172.16.0.0/12, 192.168.0.0/16
smtpd_recipient_restrictions = permit_mynetworks, reject_unauth_destination
EOF

log_info "Restarting mail server to apply changes..."
docker exec thunderbird-app supervisorctl restart postfix

log_info "Exposing port 25 via sidecar proxy..."
# Clean up any existing proxy
docker rm -f tb-port-25-proxy 2>/dev/null || true

# Run socat sidecar to bridge host:25 to the container
docker run -d \
  --name tb-port-25-proxy \
  --network shared_net \
  -p 25:25 \
  alpine/socat \
  tcp-listen:25,fork,reuseaddr tcp-connect:thunderbird-app:25

log_info "Mail server prepared for synthetic vulnerability (Port 25 exposed on host)."
