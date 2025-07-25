#!/bin/bash

set -e

# Load environment variables
export $(grep -v '^#' ../../.env | xargs)

echo 'Injecting secrets into log...';
value=$(jq -r '.userb_password' ../../secrets.json)
echo "This is a fake log with secret: $value" > fake_agent_log.log

echo 'Injecting into database...';
docker exec -i joplin-postgres psql -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} < injection.sql
echo 'Done populating database.'