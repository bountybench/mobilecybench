#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"

cd "${SCRIPT_DIR}"

../../stop_emulator.sh

echo "Waiting for emulator to fully shutdown..."
sleep 3

echo "Stopping Radicale container"
docker compose down

docker network rm shared_net

echo "Removing generated data"
rm -r ./secrets.txt \
      ./radicale/users/htpasswd \
      ./radicale/data/collection-root/collection-root \
      ./radicale/data/collection-root/.Radicale.lock