#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "moodle" "$@")
cd "$SCRIPT_DIR"

echo "Starting Docker images..."
docker network inspect shared_net >/dev/null 2>&1 || docker network create shared_net
docker compose up -d

echo "Configuring webserver..."
docker cp moodle_server.tar.gz moodle-webserver-1:/var/www
docker exec moodle-webserver-1 tar -xpzf /var/www/moodle_server.tar.gz -C /var/www/html
docker exec moodle-webserver-1 chown www-data:www-data /var/www/html/config.php
docker exec moodle-webserver-1 bash -c "echo 'DocumentRoot /var/www/html/public' > /etc/apache2/conf-enabled/moodle-root.conf"

if [ "$GITHUB_ACTIONS" = true ]; then
  echo "Running in CI. Will not change to emulator IP"
else
  echo "Configuring IP for Emulator..."
  docker exec moodle-webserver-1 sed -i 's/localhost:8000/10.0.2.2:8000/g' /var/www/html/config.php
fi

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

echo "Installing APK..."
adb_install_apk "$APK_PATH"