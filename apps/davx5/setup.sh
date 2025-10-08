#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APK_PATH="${SCRIPT_DIR}/apk/davx5.apk"

cd "$SCRIPT_DIR"

setup_backend() {
    echo "Generating users..."
    python3 "${SCRIPT_DIR}/generate_users.py"

    mkdir -p ./radicale/data/collection-root

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

        sleep 0.2

    done < <(jq -r 'keys[]' ./secrets.json)

    echo "Seeding data..."

    python3 "${SCRIPT_DIR}/seed_data.py"
}

install_davx5() {
    adb uninstall at.bitfire.davdroid 2>/dev/null || echo "No existing installation found"

    adb install -r -g "$APK_PATH"
    echo "DAVx5 installed successfully"
}

main() {
    setup_backend
    install_davx5
}

main "$@"