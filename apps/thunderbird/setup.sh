#!/bin/bash
set -e
 
pip install uiautomator2  
 
USERNAME="$(python3 -c 'import json; print(json.load(open("metadata.json"))["username"])')"
PASSWORD="$(python3 -c 'import json; print(json.load(open("metadata.json"))["password"])')"
 
MAIL_HOST="mail.test.com"   
CERT_DIR="dms-ssl/ssl"
KEY="$CERT_DIR/${MAIL_HOST}-key.pem"
CRT="$CERT_DIR/${MAIL_HOST}-cert.pem"
CACERT="$CERT_DIR/demoCA/cacert.pem"
CAKEY="$CERT_DIR/demoCA/cakey.pem"

if [[ ! -f "$KEY" || ! -f "$CRT" || ! -f "$CACERT" ]]; then
  echo "Generating self-signed TLS certs for $MAIL_HOST..."
  mkdir -p "$CERT_DIR/demoCA"
  [[ -f "$CAKEY"  ]] || openssl genrsa -out "$CAKEY" 2048 >/dev/null 2>&1
  [[ -f "$CACERT" ]] || openssl req -x509 -new -key "$CAKEY" -sha256 -days 3650 \
                        -subj "/CN=Test Root CA" -out "$CACERT" >/dev/null 2>&1
  openssl req -newkey rsa:2048 -nodes \
    -keyout "$KEY" -subj "/CN=${MAIL_HOST}" \
    -out "$CERT_DIR/${MAIL_HOST}.csr" >/dev/null 2>&1
  openssl x509 -req -in "$CERT_DIR/${MAIL_HOST}.csr" \
    -CA "$CACERT" -CAkey "$CAKEY" -CAcreateserial -days 825 -sha256 \
    -out "$CRT" >/dev/null 2>&1
fi
 

echo "Starting docker-mailserver..."
docker compose up -d
 

echo "Adding email accounts..." 
docker exec thunderbird-mail setup email add "$USERNAME" "$PASSWORD" 
# docker exec thunderbird-mail setup email add "alex@test.com" "alexpass"
# docker exec thunderbird-mail setup email add "bob@test.com" "bobpass"

# docker exec thunderbird-mail setup email list

# echo "Setting up app (APK link flow)..."
./setup_app_apklink.sh

echo "Done."
