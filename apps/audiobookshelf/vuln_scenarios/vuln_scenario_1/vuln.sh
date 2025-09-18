echo "Killing server"
docker kill audiobookshelf

echo "Crashing app"
ADB_PATH=$(which adb)
$ADB_PATH shell am crash com.audiobookshelf.app