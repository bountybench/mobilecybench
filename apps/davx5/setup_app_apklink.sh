#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "$SCRIPT_DIR"

download_davx5() {
    mkdir -p "${SCRIPT_DIR}/apk"

    download_link=$(jq -r '.download_link' "metadata.json")
    APK_PATH="apk/davx5.apk"

    curl -L -o "$APK_PATH" "$download_link"
}

main() {
    download_davx5
}

main "$@"