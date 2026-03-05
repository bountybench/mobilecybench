echo "Killing server"
docker kill nextcloud-server
docker kill nextcloud-talk-tls-proxy

echo "Crashing app"
ADB_PATH=$(which adb)
$ADB_PATH shell am crash com.nextcloud.talk2
