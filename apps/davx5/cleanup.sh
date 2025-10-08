#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "${SCRIPT_DIR}"

echo "Stopping Radicale container"

if ! docker ps --format '{{.Names}}' | grep -q '^radicale$'; then
    echo "Radicale container not running, starting temporarily..."
    docker compose up -d radicale
    sleep 2
fi

docker exec radicale chown -R $(id -u):$(id -g) /data/collection-root || true

docker compose down

docker network rm shared_net

echo "Resetting secrets.json"
rm secrets.json
touch secrets.json

echo "Removing generated data"
rm -rf ./secrets.txt \
       ./radicale/users/htpasswd \
       ./radicale/data/collection-root/collection-root \
       ./radicale/data/collection-root/.Radicale.lock