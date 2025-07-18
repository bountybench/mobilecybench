#!/bin/bash
# Start Android emulator

docker exec -it nextcloud-server php -r '
  include "/var/www/html/config/config.php";
  $CONFIG["trusted_domains"][] = "10.0.2.2:8080";
  file_put_contents("/var/www/html/config/config.php", "<?php\n\$CONFIG = " . var_export($CONFIG, true) . ";\n");
'
echo "Set permissions!"

ANDROID_HOME="${HOME}/.android-sdk"
EMULATOR_NAME="MobileCybenchEmu"

echo "Starting Android emulator: $EMULATOR_NAME"
echo "This may take a few minutes on first boot..."

"$ANDROID_HOME/emulator/emulator" \
    -avd "$EMULATOR_NAME" \
    -no-snapshot-save \
    -wipe-data \
    -gpu host \
    -skin 1080x1920 \
    -memory 2048 \
    &

echo "Emulator started in background"
echo "Waiting for device to be ready..."

# Wait for device
"$ANDROID_HOME/platform-tools/adb" wait-for-device

adb_path="${ANDROID_HOME}/platform-tools/adb"
"${adb_path}" wait-for-device
"${adb_path}" tcpip 5555
"${adb_path}" connect host.docker.internal:5555
echo "Connected!"

git clone --depth=1 --branch v21.1.1 https://github.com/nextcloud/talk-android.git
cd talk-android
./gradlew installGenericDebug
echo "Added talk app!"

echo "Device ready!"
echo "To check device status: adb devices"
