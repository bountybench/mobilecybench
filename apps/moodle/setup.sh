#!/bin/bash
set -e
# Set up server

if [ "$(basename "$PWD")" != "moodle" ]; then
  echo "Error: This script must be run from the 'apps/moodle' directory."
  exit 1
fi

echo "Starting Docker images..."
docker compose up -d

echo "Configuring webserver..."
docker cp moodle_server.tar.gz moodle-webserver-1:/var/www
docker exec moodle-webserver-1 tar -xpzf /var/www/moodle_server.tar.gz -C /var/www/html
docker exec moodle-webserver-1 chown www-data:www-data /var/www/html/config.php
docker exec moodle-webserver-1 bash -c "echo 'DocumentRoot /var/www/html/public' > /etc/apache2/conf-enabled/moodle-root.conf"

echo "Apply changes and restart web server container..."
docker restart moodle-webserver-1

if [ "$GITHUB_ACTIONS" = true ]; then
  echo "Running in CI. Will not change to emulator IP"
else
  echo "Configuring IP for Emulator..."
  docker exec moodle-webserver-1 sed -i 's/localhost:8000/10.0.2.2:8000/g' /var/www/html/config.php
fi

echo "Waiting for MySQL to respond..."
DB_PASS=$(jq -r '.dbpass' secrets.json)

until docker exec moodle-db-1 mysqladmin ping -u root -p$DB_PASS --silent &>/dev/null; do
  sleep 1
done


echo "Restoring database..."
docker exec -i moodle-db-1 mysql -u root -p$DB_PASS < backup.sql

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

# echo "Generating test environment..."
# docker exec moodle-webserver-1 bash -c 'php public/admin/tool/generator/cli/maketestsite.php --size S --fixeddataset --bypasscheck'
