echo "Killing server"
docker kill nextcloud-server

echo "Crashing app"
ADB_PATH=$(which adb)
$ADB_PATH shell am crash com.nextcloud.talk2