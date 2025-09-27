#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
VENV_DIR="${SCRIPT_DIR}/.venv"

cd "${SCRIPT_DIR}"

echo "Stopping Radicale container"
docker compose down

docker network rm shared_net

echo "Resetting secrets.json"
rm secrets.json
touch secrets.json

echo "Removing generated data"
rm -rf ./radicale/users/htpasswd \
       ./radicale/data/collection-root/collection-root \
       ./radicale/data/collection-root/.Radicale.lock

echo "Removing .venv"
rm -rf ./.venv

echo "Removing Java"
rm -rf ./java21

echo "Removing Keys"
rm -rf ./keys

echo "Removing apk & build remnants"
cd ./codebase
rm -rf ./.gradle \
      ./.kotlin \
      ./build \
      ./app/build