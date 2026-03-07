#!/bin/bash
# =============================================================================
# SSL Certificate Generation Script
# =============================================================================
# Generate CA and server certs in dms-config/ssl for mail.test.com

set -e

# =============================================================================
# Configuration
# =============================================================================

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
DOMAIN="mail.test.com"
BASE_DIR="${SCRIPT_DIR}/dms-config/ssl"
DEMO_CA_DIR="${BASE_DIR}/demoCA"
OPENSSL_EXTFILE="${BASE_DIR}/openssl-server-ext.cnf"

CA_KEY="${DEMO_CA_DIR}/cakey.pem"
CA_CERT="${DEMO_CA_DIR}/cacert.pem"
CA_SERIAL="${DEMO_CA_DIR}/cacert.srl"

SRV_KEY="${BASE_DIR}/${DOMAIN}-key.pem"
SRV_CSR="${BASE_DIR}/${DOMAIN}.csr"
SRV_CERT="${BASE_DIR}/${DOMAIN}-cert.pem"

FORCE="${FORCE:-0}"
SERVER_SAN_DNS="${SERVER_SAN_DNS:-mail.test.com}"
SERVER_SAN_IPS="${SERVER_SAN_IPS:-10.0.2.2,127.0.0.1}"

mkdir -p "${DEMO_CA_DIR}"

# =============================================================================
# Helper Functions
# =============================================================================

make_or_overwrite() {
  local path="$1"
  if [[ -f "$path" && "$FORCE" != "1" ]]; then
    return 1
  fi
  return 0
}

# =============================================================================
# Generate Certificates
# =============================================================================

echo "==> Generating SSL certificates (FORCE=${FORCE})"

# Use shared CA from repository root
CA_KEY="${SCRIPT_DIR}/../../tls/rootCA.key"
CA_CERT="${SCRIPT_DIR}/../../tls/rootCA.pem"

if [[ ! -f "$CA_KEY" || ! -f "$CA_CERT" ]]; then
    echo "ERROR: Shared Root CA not found in tls/ directory."
    exit 1
fi

# Generate server key and CSR
if make_or_overwrite "${SRV_KEY}"; then
  openssl genrsa -out "${SRV_KEY}" 2048
fi

if make_or_overwrite "${SRV_CSR}"; then
  openssl req -new -key "${SRV_KEY}" \
    -subj "/CN=${DOMAIN}" \
    -out "${SRV_CSR}"
fi

# Build server certificate extensions with SANs.
san_entries="DNS:${SERVER_SAN_DNS}"
IFS=',' read -r -a ip_array <<< "${SERVER_SAN_IPS}"
for ip in "${ip_array[@]}"; do
  ip_trimmed="$(echo "$ip" | xargs)"
  if [[ -n "${ip_trimmed}" ]]; then
    san_entries="${san_entries},IP:${ip_trimmed}"
  fi
done

cat > "${OPENSSL_EXTFILE}" <<EOF
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage=digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=${san_entries}
EOF

# Generate server certificate signed by CA
if make_or_overwrite "${SRV_CERT}"; then
  openssl x509 -req -in "${SRV_CSR}" \
    -CA "${CA_CERT}" -CAkey "${CA_KEY}" -CAcreateserial \
    -days 825 -sha256 \
    -extfile "${OPENSSL_EXTFILE}" \
    -out "${SRV_CERT}"
fi

# =============================================================================
# Create Configuration Files
# =============================================================================

touch "${SCRIPT_DIR}/dms-config/dovecot-quotas.cf"
touch "${SCRIPT_DIR}/dms-config/postfix-accounts.cf"
cat > "${SCRIPT_DIR}/dms-config/dovecot.cf" <<'EOF'
# =============================================================================
# ACL Plugin Configuration for Mailbox Access Control Testing
# =============================================================================

# Enable ACL plugin globally (must be loaded before protocol-specific plugins)
mail_plugins = acl

# ACL plugin backend configuration
plugin {
  acl = vfile
  acl_shared_dict = file:/var/lib/dovecot/shared-mailboxes
}

# Enable ACL for IMAP protocol (requires base acl plugin)
protocol imap {
  mail_plugins = acl imap_acl
}

# Shared namespace configuration to expose other users' mailboxes
# Must use same separator as default namespace (typically '.')
# list = yes makes all shared mailboxes with ACL visible
namespace shared {
  type = shared
  separator = .
  prefix = shared.%%u.
  location = maildir:%%h/Maildir:INDEXPVT=~/Maildir/shared/%%u
  subscriptions = no
  list = yes
}
EOF

# =============================================================================
# Secure Private Keys
# =============================================================================

chmod 600 "${SRV_KEY}"

echo "Done. Certificates generated in: ${BASE_DIR}"
