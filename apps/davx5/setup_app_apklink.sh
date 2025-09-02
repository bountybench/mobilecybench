#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
source "$ROOT_DIR/utils/android.sh"

cd "$SCRIPT_DIR"

install_davx5() {
    download_link=$(jq -r '.download_link' "metadata.json")
    APK_PATH="davx5.apk"

    curl -L -o "$APK_PATH" "$download_link"

    adb install "$APK_PATH"
    echo "DAVx5 installed successfully"

}

launch_davx5() {
    echo "Launching DAVx5..."
    adb_launch_activity "at.bitfire.davdroid/.ui.AppListActivity"
    echo "DAVx5 Launched"
}

main() {
    install_davx5
    launch_davx5
}

main "$@"