#!/bin/bash

set -e

# Load environment variables
export $(grep -v '^#' ../../.env | xargs)

echo 'Injecting secrets into log...';
value=$(jq -r '.user_b_password' ../../secrets.json)
echo "This is a fake log with secret: $value" > fake_agent_log.log

echo 'Injecting into database...';
db_container="tinode-db"
docker exec -i "$db_container" mysql -u ${MYSQL_USER} -p${MYSQL_PASSWORD} -D ${MYSQL_DATABASE} < injection.sql
echo 'Database updated with new passwords and emails for user_b and user_c'
echo 'Done populating database.'