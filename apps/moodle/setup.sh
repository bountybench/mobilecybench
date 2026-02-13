#!/bin/bash
set -e
# Set up server

if [ "$(basename "$PWD")" != "moodle" ]; then
  echo "Error: This script must be run from the 'apps/moodle' directory."
  exit 1
fi

echo "Starting Docker images..."
docker network inspect shared_net >/dev/null 2>&1 || docker network create shared_net
docker compose up -d

echo "Configuring webserver..."
docker cp moodle_server.tar.gz moodle-webserver-1:/var/www
docker exec moodle-webserver-1 tar -xpzf /var/www/moodle_server.tar.gz -C /var/www/html
docker exec moodle-webserver-1 bash -c "echo 'DocumentRoot /var/www/html/public' > /etc/apache2/conf-enabled/moodle-root.conf"

if [ "$GITHUB_ACTIONS" = true ]; then
  echo "Running in CI. Will not change to emulator IP"
else
  echo "Configuring IP for Emulator..."
  docker cp config.bk.php moodle-webserver-1:/var/www/html/config.php
fi

docker exec moodle-webserver-1 chown www-data:www-data /var/www/html/config.php

echo "Apply changes and restart web server container..."
docker restart moodle-webserver-1

DB_PASS=$(jq -r '.dbpass' secrets.json)

timeout 60 bash -c '
until docker exec moodle-db-1 mysqladmin ping -u root -p$DB_PASS --silent &>/dev/null; do
  echo "Waiting for MySQL to respond..."
  sleep 5
done
'
if [ $? -eq 124 ]; then
  echo "ERROR: Timed out after 60 seconds waiting for MySQL." >&2
  exit 1
fi

echo "Restoring database..."
docker cp backup.sql.tar.gz moodle-db-1:/backup.sql.tar.gz
docker exec -i moodle-db-1 tar -xvf backup.sql.tar.gz -C /
docker exec -i moodle-db-1 bash -c "mysql --max_allowed_packet=500M -u root -p$DB_PASS < /backup.sql"

echo "Waiting for emulator..."
adb wait-for-device

apk_dir="apk"
if [[ ! -d "$apk_dir" ]]; then
  echo "APK folder not found at $apk_dir. Place your app-name.apk there and re-run."
  exit 1
fi

apk=$(ls -1t "$apk_dir"/*.apk 2>/dev/null | head -n 1 || true)
if [[ -z "$apk" ]]; then
  echo "No .apk found in $apk_dir. Place your app-name.apk there and re-run."
  exit 1
fi

echo "Using APK: $(basename "$apk")"
echo "Installing APK"
adb install $apk