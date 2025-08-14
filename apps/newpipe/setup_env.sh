#!/bin/bash

set -euo pipefail

source .env # load environment variables

# start containers
echo "Starting proxy container..."
docker compose up -d
echo "Waiting for proxy to start..."
sleep 3

# setup vars
AVD="MobileCybenchEmu"
SDK="$HOME/.android-sdk"
NEWPIPE_PACKAGE="org.schabi.newpipe.debug.HEAD"

export ANDROID_SDK_ROOT="$SDK"
export PATH="$SDK/platform-tools:$SDK/emulator:$PATH"

# locate emulator binary or exit if missing
if ! command -v emulator > /dev/null; then
    if [ -x "$ANDROID_SDK_ROOT/emulator/emulator" ]; then
        EMULATOR_BIN="$ANDROID_SDK_ROOT/emulator/emulator"
    elif [ -x "$ANDROID_SDK_ROOT/tools/emulator" ]; then
        EMULATOR_BIN="$ANDROID_SDK_ROOT/tools/emulator"
    else
        echo -e "${ERROR} Emulator binary not found in $ANDROID_SDK_ROOT" >&2
        exit 1
    fi
else
    EMULATOR_BIN="emulator"
fi

echo "Setting up emulator for NewPipe proxy..."

# start the emulator with writable /system
adb emu kill >/dev/null 2>&1 || true
# use located emulator binary
$EMULATOR_BIN @"$AVD" -writable-system -no-snapshot-save &
echo "Booting $AVD …"
while ! adb shell getprop sys.boot_completed 2>/dev/null | grep -q 1; 
    do sleep 2; 
done
adb root && adb remount

# install proxy certificate from Docker container for proxy server
echo "Installing proxy certificate..."
docker cp newpipe_proxy:/home/mitmproxy/.mitmproxy/mitmproxy-ca-cert.pem ./ca-cert.pem
HASH=$(openssl x509 -inform PEM -subject_hash_old -in ca-cert.pem | head -1)
DER="$HASH.0"
openssl x509 -inform PEM -in ca-cert.pem -outform DER -out "$DER"

echo "Pushing CA into /system store"
adb shell "rm -f /system/etc/security/cacerts/$DER" || true
adb push "$DER" /system/etc/security/cacerts/
adb shell chmod 644 /system/etc/security/cacerts/"$DER"
rm "$DER" ca-cert.pem

# reload keystore
adb shell 'stop keystore && start keystore' || {
    adb reboot
    while ! adb shell getprop sys.boot_completed | grep -q 1; 
        do sleep 2; 
    done
}

# set proxy to point to Docker container
echo "Setting proxy to 10.0.2.2:${PROXY_PORT}..."
adb shell settings put global http_proxy 10.0.2.2:${PROXY_PORT}
adb shell settings put global https_proxy 10.0.2.2:${PROXY_PORT}

echo "Environment setup complete. Proxy running on port ${PROXY_PORT}"