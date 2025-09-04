#!/bin/bash
# Generate CA and server certs in dms-config/ssl for mail.test.com 

set -e 

# Absolute path to the directory where this script is located
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

# whether to force overwrite existing files
FORCE="${FORCE:-0}"

mkdir -p "${DEMO_CA_DIR}"

make_or_overwrite() {
  local path="$1"
  if [[ -f "$path" && "$FORCE" != "1" ]]; then
    return 1
  fi
  return 0
}

echo "==> Generating files under ${BASE_DIR} (FORCE=${FORCE})"

# 1) CA key + cert
if make_or_overwrite "${CA_KEY}"; then
  echo " • CA private key"
  openssl genrsa -out "${CA_KEY}" 2048
fi

if make_or_overwrite "${CA_CERT}"; then
  echo " • CA certificate"
  openssl req -x509 -new -key "${CA_KEY}" -sha256 -days 3650 \
    -subj "/CN=Test Root CA" \
    -out "${CA_CERT}"
fi

# 2) Server key + CSR
if make_or_overwrite "${SRV_KEY}"; then
  echo " • Server private key"
  openssl genrsa -out "${SRV_KEY}" 2048
fi

if make_or_overwrite "${SRV_CSR}"; then
  echo " • Server CSR"
  openssl req -new -key "${SRV_KEY}" \
    -subj "/CN=${DOMAIN}" \
    -out "${SRV_CSR}"
fi

# 3) Server cert signed by CA
if make_or_overwrite "${SRV_CERT}"; then
  echo " • Server certificate"
  openssl x509 -req -in "${SRV_CSR}" \
    -CA "${CA_CERT}" -CAkey "${CA_KEY}" -CAcreateserial \
    -days 825 -sha256 -out "${SRV_CERT}"
fi

# 4) Empty config files
touch "${SCRIPT_DIR}/dms-config/dovecot-quotas.cf"
touch "${SCRIPT_DIR}/dms-config/postfix-accounts.cf"

# 5) Secure private keys
chmod 600 "${CA_KEY}" "${SRV_KEY}"

echo
echo "Done. Certificates and configs are in: ${BASE_DIR}"
