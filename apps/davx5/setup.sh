#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

cd "$SCRIPT_DIR"

if [[ ! -d "$VENV_DIR" ]]; then
    echo "Creating Python virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

echo "Installing Python dependencies..."
pip install uiautomator2 bcrypt

echo "Running setup scripts..."
python3 "${SCRIPT_DIR}/generate_users.py"

python3 "${SCRIPT_DIR}/seed_data.py"

docker compose up -d

./setup_app_apklink.sh