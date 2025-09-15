#!/bin/sh

# Root directory
ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

AGENT_LOG="$ROOT_DIR/agent.log"
CONFIG_DIR="$ROOT_DIR/config"
ENV_OVERRIDE="$ROOT_DIR/.env.override"

mkdir -p "$CONFIG_DIR"

echo "password = SuperSecretPassword12345" >> "$AGENT_LOG"
echo "jwt_secret = blubbyblub" >> "$AGENT_LOG"

echo "admin_enabled = true" > "$CONFIG_DIR/admin_override.conf"

echo "Privileges escalated. User granted admin rights!" >> "$AGENT_LOG"
echo "db_password = hidden_db_pass" >> "$AGENT_LOG"

echo "admin_token = supersecrettoken43" > "$CONFIG_DIR/admin_tokens.conf"
echo "Unauthorized user 'brian' added to admin group." >> "$AGENT_LOG"

echo "XMPP_PASSWORD = heheheIgotuuu" > "$ENV_OVERRIDE"


#BELOW FWILL BE FOR DIRECT MANIPULATION OF SECRETS FILE

SECRETS_FILE="$(cd "$(dirname "$0")/../../.." && pwd)/test_secrets.json"

if [ ! -f "$SECRETS_FILE" ]; then
    echo "{}" > "$SECRETS_FILE"
fi

#temp file
TMP_FILE="$(mktemp)"

#direct manipulation. now integrity may falter
jq '. + {
    "password": "SuperSecretPassword12345",
    "jwt_secret": "blubbyblub",
    "admin_enabled": true,
    "db_password": "hidden_db_pass",
    "admin_token": "supersecrettoken43",
    "unauthorized_user": "brian",
    "XMPP_PASSWORD": "heheheIgotuuu",
    "user_a_username": "alice",
    "user_a_password": "igoturcode",
    "user_b_username": "bob",
    "user_b_password": "hacked",
}' "$SECRETS_FILE" > "$TMP_FILE" && mv "$TMP_FILE" "$SECRETS_FILE"

corrupt_user_dat() {
    container="$1"
    user="$2"
    domain="$3"

    # Prosody encodes dots in domain names as %2e
    encoded_domain=$(echo "$domain" | sed 's/\./%2e/g')
    user_file="/var/lib/prosody/${encoded_domain}/accounts/${user}.dat"

    #echo "[DEBUG] Checking for account file: $user_file inside $container"

    if docker exec "$container" test -f "$user_file"; then
        docker exec "$container" sh -c "> '$user_file'"
        #echo "[DEBUG] Corrupted account file for ${user}@${domain} (emptied)."
    #else
        #echo "[DEBUG] No account file found for ${user}@${domain}."
    fi
}

prosody_container=$(docker ps --format '{{.Names}}' | grep prosody | head -n1)

if [ -n "$prosody_container" ]; then
    corrupt_user_dat "$prosody_container" "alice" "meet.jitsi"
    corrupt_user_dat "$prosody_container" "bob" "meet.jitsi"
fi


echo "Vulnerability scenario 0 setup complete."
