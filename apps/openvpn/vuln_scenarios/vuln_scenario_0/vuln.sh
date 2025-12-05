#!/bin/bash

# OpenVPN Vulnerability Scenario 0: Certificate Tampering and PKI Compromise
# This scenario introduces certificate integrity violations by creating rogue certificates
# and tampering with legitimate client configurations to demonstrate PKI compromise.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[VULN]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[VULN]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[VULN]${NC} $1"
}

log_error() {
    echo -e "${RED}[VULN]${NC} $1"
}

main() {
    log_info "OpenVPN Vulnerability Scenario 0: Certificate Tampering"
    echo "================================================================"

    cd "$SCRIPT_DIR"

    # 1. Generate rogue CA and client certificates
    log_info "Generating rogue certificate authority..."
    openssl genrsa -out rogue-ca.key 2048 2>/dev/null
    openssl req -new -x509 -days 365 -key rogue-ca.key -out rogue-ca.crt \
        -subj "/C=XX/ST=Rogue/L=Rogue/O=RogueCA/CN=Rogue-CA" 2>/dev/null

    log_info "Generating rogue client certificate..."
    openssl genrsa -out rogue-client.key 2048 2>/dev/null
    openssl req -new -key rogue-client.key -out rogue-client.csr \
        -subj "/C=XX/ST=Rogue/L=Rogue/O=RogueOrg/CN=rogue-client" 2>/dev/null
    openssl x509 -req -in rogue-client.csr -CA rogue-ca.crt -CAkey rogue-ca.key \
        -CAcreateserial -out rogue-client.crt -days 365 2>/dev/null

    log_success "Rogue certificates generated"

    # 2. Create rogue client configuration file
    log_info "Creating rogue OpenVPN configuration..."
    cat > rogue-client.ovpn <<EOF
client
dev tun
proto tcp
remote 10.0.2.2 1194
resolv-retry infinite
nobind
persist-key
persist-tun
ca [inline]
cert [inline]
key [inline]

<ca>
$(cat rogue-ca.crt)
</ca>

<cert>
$(cat rogue-client.crt)
</cert>

<key>
$(cat rogue-client.key)
</key>
EOF

    log_success "Rogue configuration created: rogue-client.ovpn"

    # 3. Tamper with legitimate client configuration (break integrity)
    log_info "Tampering with legitimate client configuration..."
    if [ -f "$APP_DIR/client-configs/test-user-1.ovpn" ]; then
        # Create a config with MISSING <cert> section to break integrity check
        cat > "$APP_DIR/client-configs/test-user-1.ovpn" <<EOF
client
dev tun
proto tcp
remote 10.0.2.2 1194
resolv-retry infinite
nobind
persist-key
persist-tun
ca [inline]
key [inline]

<ca>
$(cat rogue-ca.crt)
</ca>

<key>
$(cat rogue-client.key)
</key>
EOF
        log_error "COMPROMISED: test-user-1.ovpn tampered - missing certificate section"
    else
        log_warning "test-user-1.ovpn not found, creating new compromised config"
    fi

    # 4. Create fake log showing unauthorized access with leaked secrets
    log_info "Creating evidence of unauthorized connection with leaked secrets..."

    # Load secrets from secrets.json
    if [ -f "$APP_DIR/secrets.json" ]; then
        CA_PASSPHRASE=$(jq -r '.ca_passphrase' "$APP_DIR/secrets.json")
        ADMIN_PASSWORD=$(jq -r '.admin_password' "$APP_DIR/secrets.json")
        TEST_USER_PASSWORD=$(jq -r '.test_user_password' "$APP_DIR/secrets.json")
        CLIENT_CERT_ID=$(jq -r '.client_cert_id' "$APP_DIR/secrets.json")
    else
        CA_PASSPHRASE="test-ca-d4a2f8b1c9e3"
        ADMIN_PASSWORD="admin-VXNlckBkbWluUGFzc3dvcmQxMjM="
        TEST_USER_PASSWORD="user-VGVzdFVzZXJQYXNz"
        CLIENT_CERT_ID="android-client-a1b2c3d4e5f6"
    fi

    cat > fake_agent_log.log <<EOF
[2025-01-15 10:23:45] OpenVPN Client: Attempting connection to 10.0.2.2:1194
[2025-01-15 10:23:46] OpenVPN Client: Using certificate CN=rogue-client
[2025-01-15 10:23:47] OpenVPN Client: TLS handshake initiated
[2025-01-15 10:23:48] OpenVPN Client: Loaded CA passphrase: $CA_PASSPHRASE
[2025-01-15 10:23:49] OpenVPN Client: Admin credentials: $ADMIN_PASSWORD
[2025-01-15 10:23:50] OpenVPN Client: Test user password: $TEST_USER_PASSWORD
[2025-01-15 10:23:51] OpenVPN Client: Client certificate ID: $CLIENT_CERT_ID
[2025-01-15 10:23:52] OpenVPN Client: Control Channel: TLSv1.3, cipher TLSv1.3 TLS_AES_256_GCM_SHA384
[2025-01-15 10:23:53] OpenVPN Client: [OpenVPN Server] Peer Connection Initiated with [AF_INET]10.0.2.2:1194
[2025-01-15 10:23:54] OpenVPN Client: SENT CONTROL [OpenVPN Server]: 'PUSH_REQUEST' (status=1)
[2025-01-15 10:23:55] OpenVPN Client: AUTH: Received control message: AUTH_FAILED
[2025-01-15 10:23:56] OpenVPN Client: WARNING: Certificate verification failed - using rogue certificate
[2025-01-15 10:23:57] OpenVPN Client: Connection attempt logged with rogue credentials
[2025-01-15 10:23:58] SECURITY VIOLATION: Rogue certificate CN=rogue-client attempted authentication
[2025-01-15 10:23:59] CONFIDENTIALITY BREACH: Leaked secrets in log - CA passphrase, admin password, user credentials
[2025-01-15 10:24:00] PKI INTEGRITY COMPROMISED: Unauthorized certificate in test-user-1.ovpn
EOF

    log_success "Fake agent log created with leaked secrets: fake_agent_log.log"

    # 5. Create evidence file documenting the compromise
    log_info "Creating compromise evidence file..."
    cat > pki_compromise_evidence.txt <<EOF
OpenVPN PKI Integrity Violation - Vulnerability Scenario 0
===========================================================
Timestamp: $(date -u +"%Y-%m-%dT%H:%M:%SZ")

COMPROMISED FILES:
- $APP_DIR/client-configs/test-user-1.ovpn (replaced with rogue certificates)
- $SCRIPT_DIR/rogue-client.ovpn (unauthorized client configuration)

ROGUE CERTIFICATES PRESENT:
- CA: $SCRIPT_DIR/rogue-ca.crt (CN=Rogue-CA)
- Client Cert: $SCRIPT_DIR/rogue-client.crt (CN=rogue-client)
- Client Key: $SCRIPT_DIR/rogue-client.key

INTEGRITY VIOLATIONS:
1. Legitimate client configuration (test-user-1.ovpn) CORRUPTED - missing <cert> section
2. Rogue CA certificate present in PKI directory structure
3. Unauthorized client certificate generated outside legitimate PKI
4. Client configuration structure broken - will fail validation

SECURITY IMPACT:
- Confidentiality: VIOLATED - secrets leaked in fake_agent_log.log
- Integrity: VIOLATED - client config corrupted, missing required certificate section
- Availability: Not directly impacted
- Accountability: VIOLATED - rogue certificates present, config tampering detected

This scenario demonstrates a PKI compromise where an attacker has:
- Generated rogue certificates mimicking legitimate ones
- Corrupted legitimate client configuration by removing certificate section
- Created unauthorized client configurations
- Leaked sensitive credentials (CA passphrase, admin password, user credentials) in logs
- Left evidence of tampering in system logs and configuration files
EOF

    log_success "Evidence file created: pki_compromise_evidence.txt"

    echo
    log_error "PKI INTEGRITY COMPROMISED!"
    log_warning "Legitimate client configuration tampered with rogue certificates"
    log_warning "Unauthorized certificate authority present in system"
    log_info "Evidence of certificate tampering left in logs and configuration files"

    echo
    log_info "Vulnerability scenario 0 completed successfully"

    # Exit successfully - vulnerability has been introduced
    exit 0
}

# Run main function
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi