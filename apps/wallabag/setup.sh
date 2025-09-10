#!/bin/bash
set -e

echo "[Wallabag] MobileCybench setup begin..."

# --- Dependency checks (adb, docker, gradle, etc) ---

DEPENDENCIES=(adb docker)
for dep in "${DEPENDENCIES[@]}"; do
    if ! command -v $dep >/dev/null 2>&1; then
        echo "Error: $dep is required but not installed."
        exit 1
    fi
done

export ANDROID_HOME="${ANDROID_HOME:-$HOME/.android-sdk}"
export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"

# --- Start backend (docker) ---
echo "[Wallabag] Starting backend server (Docker)..."
docker run -d --name wallabag-server -v /opt/wallabag/data:/var/www/wallabag/data -v /opt/wallabag/images:/var/www/wallabag/web/assets/images -p 8080:80 -e "SYMFONY__ENV__DOMAIN_NAME=http://10.0.2.2:8080" wallabag/wallabag

sleep 10
echo "[Wallabag] Backend should be up at http://10.0.2.2:8080"

# --- Setup Android app APK ---
echo "[Wallabag] Building APK..."
./setup_app_source.sh

APK=wallabag-debug.apk

if [ ! -f "$APK" ]; then
    echo "Error: APK not found after build!"
    exit 1
fi

# --- Ensure emulator is running ---
if ! adb devices | grep -w "emulator" >/dev/null; then
    echo "[Wallabag] Starting emulator..."
    EMU="$ANDROID_HOME/emulator/emulator"
    AVD_NAME=$($EMU -list-avds | head -n 1)
    if [ -z "$AVD_NAME" ]; then
        echo "Error: No AVDs found."
        exit 1
    fi
    $EMU -avd "$AVD_NAME" -no-snapshot-load -no-audio -no-window &
    sleep 40
fi

# --- Install APK on emulator ---
adb install -r "$APK"

echo "[Wallabag] APK installed successfully."
echo "[Wallabag] Setup script complete."
