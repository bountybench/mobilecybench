#!/bin/bash
# =============================================================================
# Setup Script for Thunderbird Environment
# =============================================================================

set -e

# =============================================================================
# Install Dependencies
# =============================================================================

pip install -q uiautomator2

# =============================================================================
# Generate SSL Certificates
# =============================================================================

./generate_ssl.sh

# =============================================================================
# Configure Mail Server Users
# =============================================================================

USERA_EMAIL=$(jq -r .username metadata.json)
USERA_PW=$(jq -r .password metadata.json)
USERB_PW=$(jq -r .userb_password secrets.json)

# Create password hashes
: > dms-config/postfix-accounts.cf
HASH_USERA=$(docker run --rm mailserver/docker-mailserver:15.1.0 bash -lc "doveadm pw -s SHA512-CRYPT -p '$USERA_PW'")
HASH_USERB=$(docker run --rm mailserver/docker-mailserver:15.1.0 bash -lc "doveadm pw -s SHA512-CRYPT -p '$USERB_PW'")
printf "%s|%s\n" "$USERA_EMAIL" "$HASH_USERA" >> dms-config/postfix-accounts.cf
printf "%s|%s\n" "userb@test.com" "$HASH_USERB" >> dms-config/postfix-accounts.cf

# =============================================================================
# Start Mail Server
# =============================================================================

docker compose up -d
timeout 60 bash -c 'until docker compose ps | grep -q "healthy"; do sleep 2; done'
docker compose run --rm seeder

# =============================================================================
# Install APK
# =============================================================================

if [ ! -d "apk" ]; then
    echo "ERROR: apk/ directory does not exist"
    exit 1
fi

APK_COUNT=$(find apk -maxdepth 1 -name "*.apk" -type f 2>/dev/null | wc -l)

if [ "$APK_COUNT" -eq 0 ]; then
    echo "ERROR: No APK found in apk/ directory"
    exit 1
fi

APK_PATH=$(find apk -maxdepth 1 -name "*.apk" -type f 2>/dev/null | head -n 1)

if [ -z "$APK_PATH" ]; then
    echo "ERROR: Failed to locate APK file"
    exit 1
fi

adb install -r -g "$APK_PATH"
echo "Setup complete."
