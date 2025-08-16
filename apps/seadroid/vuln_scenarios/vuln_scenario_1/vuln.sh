echo "Killing server"
docker compose stop caddy

echo "Crashing app"
ADB_PATH=$(which adb)
$ADB_PATH shell am crash net.seafile.seadroid2