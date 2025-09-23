#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
VENV_DIR="$SCRIPT_DIR/.venv"
source "$ROOT_DIR/utils/android.sh"

cd "$SCRIPT_DIR"

source "$VENV_DIR/bin/activate"

download_davx5() {
    mdkir -p "${SCIPT_DIR}/apk"

    download_link=$(jq -r '.download_link' "metadata.json")
    APK_PATH="${SCRIPT_DIR}/apk/davx5.apk"

    curl -L -o "$APK_PATH" "$download_link"

}

main() {
    download_davx5
}

main "$@"