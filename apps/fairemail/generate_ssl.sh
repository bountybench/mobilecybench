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

CA_KEY="${DEMO_CA_DIR}/cakey.pem"
CA_CERT="${DEMO_CA_DIR}/cacert.pem"
CA_SERIAL="${DEMO_CA_DIR}/cacert.srl"

SRV_KEY="${BASE_DIR}/${DOMAIN}-key.pem"
SRV_CSR="${BASE_DIR}/${DOMAIN}.csr"
SRV_CERT="${BASE_DIR}/${DOMAIN}-cert.pem"

FORCE="${FORCE:-0}"

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

# Generate CA key and certificate
if make_or_overwrite "${CA_KEY}"; then
  openssl genrsa -out "${CA_KEY}" 2048
  openssl req -x509 -new -nodes -key "${CA_KEY}" -sha256 -days 3650 -out "${CA_CERT}" -subj "/CN=MyCustomCA"
  echo "01" > "${CA_SERIAL}"
  echo "Created CA: ${CA_CERT}"
else
  echo "Skipping CA generation (exists)"
fi

# Generate Server key and CSR
if make_or_overwrite "${SRV_KEY}"; then
  openssl genrsa -out "${SRV_KEY}" 2048
  openssl req -new -key "${SRV_KEY}" -out "${SRV_CSR}" -subj "/CN=${DOMAIN}/O=MyOrg"
  echo "Created Server CSR: ${SRV_CSR}"
else
  echo "Skipping Server Key/CSR generation (exists)"
fi

# Sign Server Certificate with CA
if make_or_overwrite "${SRV_CERT}"; then
  openssl x509 -req -in "${SRV_CSR}" -CA "${CA_CERT}" -CAkey "${CA_KEY}" -CAserial "${CA_SERIAL}" -out "${SRV_CERT}" -days 3650 -sha256
  echo "Created Server Cert: ${SRV_CERT}"
else
  echo "Skipping Server Cert signing (exists)"
fi

echo "==> Certificate generation complete."
