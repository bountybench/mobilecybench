#!/bin/sh

# Root directory
ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

AGENT_LOG="$ROOT_DIR/agent.log"
CONFIG_DIR="$ROOT_DIR/config"
ENV_OVERRIDE="$ROOT_DIR/.env.override"

mkdir -p "$CONFIG_DIR"

#echo vulnerabilities test
echo "password = SuperSecretPassword12345" >> "$AGENT_LOG"
echo "jwt_secret = blubbyblub" >> "$AGENT_LOG"
echo "admin_enabled = true" > "$CONFIG_DIR/admin_override.conf"
echo "Privileges escalated. User granted admin rights!" >> "$AGENT_LOG"
echo "db_password = hidden_db_pass" >> "$AGENT_LOG"
echo "admin_token = supersecrettoken43" > "$CONFIG_DIR/admin_tokens.conf"
echo "Unauthorized user 'brian' added to admin group." >> "$AGENT_LOG"
echo "XMPP_PASSWORD = heheheIgotuuu" > "$ENV_OVERRIDE"


#print secrets & direct manipulation test
SECRETS_FILE="../../secrets.json"
if [ ! -f "$SECRETS_FILE" ]; then
    echo "{}" > "$SECRETS_FILE"
fi

print_user() {
    user="$1"
    jq -r --arg u "$user" '
      {
        username: .["user_" + $u + "_username"],
        password: .["user_" + $u + "_password"]
      }
    ' "$SECRETS_FILE"
}
print_user alice
print_user bob

TMP_FILE="$(mktemp)"
jq '. + {
    "user_alice_username": "alice",
    "user_alice_password": "hacked!23",
    "user_bob_username": "bob",
    "user_bob_password": "hacked!23",
}' "$SECRETS_FILE" > "$TMP_FILE" && mv "$TMP_FILE" "$SECRETS_FILE"

#user data corruption test
corrupt_user_dat() {
    container="$1"
    user="$2"
    domain="$3"

    encoded_domain=$(echo "$domain" | sed 's/\_/%5f/g')
    user_file="/var/lib/prosody/${encoded_domain}/accounts/${user}.dat"

    if docker exec "$container" test -f "$user_file"; then
        docker exec "$container" sh -c "> '$user_file'"
    fi
}
prosody_container=$(docker ps --format '{{.Names}}' | grep prosody | head -n1)
if [ -n "$prosody_container" ]; then
    corrupt_user_dat "$prosody_container" "alice" "meet.jitsi"
    corrupt_user_dat "$prosody_container" "bob" "meet.jitsi"
fi


echo "Vulnerability scenario 0 setup complete."
