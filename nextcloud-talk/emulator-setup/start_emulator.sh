# #!/bin/bash
# # Start Android emulator - must be version 34
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
# "${adb_path}" connect host.docker.internal:5555
echo "Connected!"

echo "Device ready!"
echo "To check device status: adb devices"