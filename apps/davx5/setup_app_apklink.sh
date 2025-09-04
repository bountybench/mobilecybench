#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
VENV_DIR="$SCRIPT_DIR/.venv"
source "$ROOT_DIR/utils/android.sh"

cd "$SCRIPT_DIR"

source "$VENV_DIR/bin/activate"

install_davx5() {
    download_link=$(jq -r '.download_link' "metadata.json")
    APK_PATH="davx5.apk"

    curl -L -o "$APK_PATH" "$download_link"

    adb install -r -g "$APK_PATH"
    echo "DAVx5 installed successfully"

}

launch_davx5() {
    emulator_server=$(jq -r '.emulator_server' "metadata.json")
    username=$(jq -r '.username' "metadata.json")
    password=$(jq -r '.password' "metadata.json")

    echo "Launching DAVx5..."
    
    python3 davx5_login.py \
        --server-url "${emulator_server}" \
        --username "${username}" \
        --password "${password}" \
        --verbose

    echo "DAVx5 Launched"
}

main() {
    echo "Starting emulator..."
    "${ROOT_DIR}/start_emulator.sh"

    echo "Waiting for Android system to fully boot..."
    adb shell 'while [[ -z $(getprop sys.boot_completed) ]]; do sleep 1; done'
    echo "Android system ready!"

    install_davx5
    launch_davx5
}

main "$@"