#!/usr/bin/env bash
set -euo pipefail

# Regenerate the TLS server certificate for MobileCybench local HTTPS proxies.
#
# Reuses the existing root CA and server key. The server cert is limited to
# 397 days (Chromium WebView rejects anything longer).
# See: https://chromium.googlesource.com/chromium/src/+/HEAD/net/docs/certificate_lifetimes.md
#
# Usage: ./generate_certs.sh

cd "$(dirname "${BASH_SOURCE[0]}")"

SANS="IP:10.0.2.2,IP:127.0.0.1,DNS:localhost,DNS:host.docker.internal"

for f in rootCA.pem rootCA.key server.key; do
    [[ -f "$f" ]] || { echo "Error: $f not found." >&2; exit 1; }
done

openssl req -new -key server.key -subj "/CN=10.0.2.2" \
    | openssl x509 -req -CA rootCA.pem -CAkey rootCA.key -set_serial "0x$(openssl rand -hex 16)" \
        -days 397 -sha256 \
        -extfile <(printf "subjectAltName=%s\nbasicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth" "$SANS") \
        -out server.crt

echo ""
openssl x509 -in server.crt -noout -dates -subject
