#!/bin/bash

set -e

BITWARDEN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../.."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$BITWARDEN_DIR/.env"
SECRETS_FILE="$BITWARDEN_DIR/secrets.json"
OUTPUT_LOG="$SCRIPT_DIR/fake_agent_log.log"

# Load environment variables from the correct path
if [ -f "$ENV_FILE" ]; then
    export $(grep -v '^#' "$ENV_FILE" | xargs)
else
    echo "Error: .env file not found at $ENV_FILE"
    exit 1
fi

echo 'Injecting secrets into log...'
# Extract master password from the first user in the users array
value=$(jq -r '.users[0].master_password' "$SECRETS_FILE")
echo "This is a fake log with secret: $value" > "$OUTPUT_LOG"

echo 'Injecting into database...'
echo "$SCRIPT_DIR"
# Correctly reference the docker-compose setup for bitwarden and use correct host env vars
docker exec -i vaultwarden-db psql -U ${DB_USER} -d ${DB_NAME} < "$SCRIPT_DIR/injection.sql"
echo 'Done populating database.'