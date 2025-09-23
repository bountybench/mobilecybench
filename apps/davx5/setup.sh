#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
APK_PATH="${SCRIPT_DIR}/apk/davx5.apk"
VENV_DIR="${SCRIPT_DIR}/.venv"

cd "${SCRIPT_DIR}"

setup_venv() {
    if [[ ! -d "${VENV_DIR}" ]]; then
        echo "Creating Python virtual environment..."
        python3 -m venv "${VENV_DIR}"
    fi

    source "${VENV_DIR}/bin/activate"

    echo "Installing Python dependencies..."
    pip install uiautomator2 bcrypt
}

setup_backend() {
    echo "Generating users..."
    python3 "${SCRIPT_DIR}/generate_users.py"

    mkdir -p ./radicale/data/collection-root

    docker network create shared_net

    echo "Running docker compose..."
    docker compose up -d --wait

    while IFS= read -r username; do
        password=$(jq -r ".[\"$username\"]" ./secrets.json)

        curl -u ${username}:${password} \
        -X MKCOL http://localhost:5232/${username}/calendar \
        -H "Content-Type: application/xml; charset=utf-8" \
        --data-binary '<?xml version="1.0" encoding="utf-8"?><D:mkcol xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"><D:set><D:prop><D:resourcetype><D:collection/><C:calendar/></D:resourcetype></D:prop></D:set></D:mkcol>'

        curl -u ${username}:${password} \
        -X MKCOL http://localhost:5232/${username}/contacts \
        -H "Content-Type: application/xml; charset=utf-8" \
        --data-binary '<?xml version="1.0" encoding="utf-8"?><D:mkcol xmlns:D="DAV:" xmlns:CR="urn:ietf:params:xml:ns:carddav"><D:set><D:prop><D:resourcetype><D:collection/><CR:addressbook/></D:resourcetype></D:prop></D:set></D:mkcol>'

    done < <(jq -r 'keys[]' ./secrets.json)

    echo "Seeding data..."

    python3 "${SCRIPT_DIR}/seed_data.py"
}

# boot_emulator() {
#     echo "Starting emulator..."
#     "${ROOT_DIR}/start_emulator.sh"

#     echo "Waiting for Android system to fully boot..."
#     adb shell 'while [[ -z $(getprop sys.boot_completed) ]]; do sleep 1; done'
#     echo "Android system ready!"
# }

install_davx5() {
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

    deactivate # deactivating the .venv
}

main() {
    setup_venv
    setup_backend
    ./setup_app_source.sh # or use ./setup_app_apklink.sh for no gradle build
    # boot_emulator
    install_davx5
    launch_davx5
}

main "$@"