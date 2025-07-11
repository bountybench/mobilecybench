#!/usr/bin/env bash
set -e

# config
AVD="MobileCybenchEmu"
PORT=8082
FLOW_DIR="./flows"
VENV=".venv_mitm"
SDK="$HOME/.android-sdk"

export ANDROID_SDK_ROOT="$SDK"
export PATH="$SDK/platform-tools:$SDK/emulator:$PATH"

# ensure local venv + mitmproxy
if [[ ! -d $VENV ]]; then
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q "mitmproxy>=10" "bcrypt<4.1"
fi
# shellcheck disable=SC1090
source "$VENV/bin/activate"

# make sure the mitmproxy CA exists (regenerate if lost)
CA="$HOME/.mitmproxy/mitmproxy-ca-cert.pem"
if [[ ! -f $CA ]]; then
  echo "Generating a fresh mitmproxy CA …"
  mitmdump -q --listen-port 0 --quit # creates ~/.mitmproxy
fi
[[ -f $CA ]] || { echo "Could not create mitmproxy CA"; exit 1; }

# start the emulator with writable /system
adb emu kill >/dev/null 2>&1 || true
emulator @"$AVD" -writable-system -no-snapshot-save &
echo "Booting $AVD …"
until adb shell getprop sys.boot_completed 2>/dev/null | grep -q 1; do sleep 2; done
adb root  && adb remount

# install (or replace) the CA in the system store
HASH=$(openssl x509 -inform PEM -subject_hash_old -in "$CA" | head -1)
DER="$HASH.0"
openssl x509 -inform PEM -in "$CA" -outform DER -out "$DER"

echo "Pushing CA into /system store"
adb shell "rm -f /system/etc/security/cacerts/$DER" # remove stale copy, if any
adb push "$DER" /system/etc/security/cacerts/
adb shell chmod 644 /system/etc/security/cacerts/"$DER"
rm "$DER"

# Reload keystore (faster) – fall back to full reboot if this ever fails
adb shell 'stop keystore && start keystore' || adb reboot && \
  until adb shell getprop sys.boot_completed | grep -q 1; do sleep 2; done

# configure global proxy
adb shell settings put global http_proxy 10.0.2.2:$PORT
adb shell settings put global https_proxy 10.0.2.2:$PORT

# launch interactive mitmproxy UI
mkdir -p "$FLOW_DIR"
echo "Proxy ready on :$PORT – press q in the UI to quit"
exec mitmproxy -p $PORT --set flows_dir="$FLOW_DIR" --set block_global=false

echo "setup complete"

wait