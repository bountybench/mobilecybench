#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"

cd "${SCRIPT_DIR}"

if [[ ! -d "${VENV_DIR}" ]]; then
    echo "Creating Python virtual environment..."
    python3 -m venv "${VENV_DIR}"
fi

source "${VENV_DIR}/bin/activate"

echo "Installing Python dependencies..."
pip install uiautomator2 bcrypt

echo "Generating users..."
python3 "${SCRIPT_DIR}/generate_users.py"

mkdir -p ./radicale/data/collection-root

docker network create shared_net

echo "Running docker compose..."
docker compose up -d --wait

while read -r line; do
    username="${line%%:*}"
    password="${line#*:}"

    curl -u ${username}:${password} \
    -X MKCOL http://localhost:5232/${username}/calendar \
    -H "Content-Type: application/xml; charset=utf-8" \
    --data-binary '<?xml version="1.0" encoding="utf-8"?><D:mkcol xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"><D:set><D:prop><D:resourcetype><D:collection/><C:calendar/></D:resourcetype></D:prop></D:set></D:mkcol>'

    curl -u ${username}:${password} \
    -X MKCOL http://localhost:5232/${username}/contacts \
    -H "Content-Type: application/xml; charset=utf-8" \
    --data-binary '<?xml version="1.0" encoding="utf-8"?><D:mkcol xmlns:D="DAV:" xmlns:CR="urn:ietf:params:xml:ns:carddav"><D:set><D:prop><D:resourcetype><D:collection/><CR:addressbook/></D:resourcetype></D:prop></D:set></D:mkcol>'

done < ./secrets.txt

echo "Seeding data..."
python3 "${SCRIPT_DIR}/seed_data.py"

deactivate

./setup_app_apklink.sh