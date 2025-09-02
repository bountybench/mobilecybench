#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "$SCRIPT_DIR"

python3 "${SCRIPT_DIR}/generate_users.py"

python3 "${SCRIPT_DIR}/seed_data.py"

docker compose up -d

./setup_app_apklink