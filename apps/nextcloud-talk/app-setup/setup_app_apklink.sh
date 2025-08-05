echo "Installing app on android emulator."
    
# Check if emulator is running
if ! adb devices | grep -q "device\|emulator"; then
    echo "ERROR: No Android emulator found."
    echo "Please start the emulator first."
    exit 1
fi

# Install APK with link
APK_PATH="nextcloud-talk.apk"
download_link="https://github.com/nextcloud/talk-android/releases/download/v21.1.2/nextcloud-talk-21.1.2.apk"
if [[ ! -f "$APK_PATH" ]]; then
    echo "Downloading using download link for version $version: $download_link"
    curl -L -o "$APK_PATH" "$download_link"
fi

if [[ ! -f $APK_PATH ]]; then
    echo "ERROR: APK not found at $APK_PATH"
    exit 1
fi

adb install "$APK_PATH"

echo "Nextcloud Talk was installed successfully."

chmod +x emulator_connection.sh
./emulator_connection.sh