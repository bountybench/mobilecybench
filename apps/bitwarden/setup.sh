#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_NAME="com.x8bit.bitwarden"

echo === RUNNING setup.sh ===

# Detect CI environment
is_github_ci() {
    [[ -n "$GITHUB_ACTIONS" ]] || [[ -n "$CI" ]] || [[ -n "$GITHUB_RUN_ID" ]]
}

# Check if Bitwarden app is installed on the emulator
echo "[INFO] Checking if Bitwarden app is installed on the emulator..."
if adb shell pm list packages | grep -q "$PKG_NAME"; then
    echo "✅ Bitwarden app is already installed on the emulator."
else
    echo "[INFO] Bitwarden app not found."
    # In CI, always run setup_app_apk.sh to ensure fresh installation
    if is_github_ci; then
        echo "[INFO] Running in GitHub CI"
        echo "[INFO] Running setup_app_apk.sh to install and launch it..."
        "${SCRIPT_DIR}/setup_app_apk.sh"
        echo "✅ Bitwarden app reinstalled and launched for CI."
    else
        echo "[INFO] Running setup_app_source.sh to install and launch it..."
        # "${SCRIPT_DIR}/setup_app_source.sh"
        "${SCRIPT_DIR}/setup_app_apk.sh"
        echo "✅ Bitwarden app installed and launched."
    fi
fi

# Install Python requirements
echo "[INFO] Installing Python requirements..."
pip install -r "${SCRIPT_DIR}/requirements.txt"
echo "✅ Python requirements installed."

# Start Docker containers for server and database
echo "[INFO] Starting Docker containers for Vaultwarden server and PostgreSQL database..."
docker compose up --build -d
echo "✅ Docker containers started."

# Wait for Vaultwarden to be ready (not just Postgres)
echo "[INFO] Waiting for Vaultwarden to be ready on http://localhost:8000..."
until curl -sf http://localhost:8000 > /dev/null; do
  sleep 2
done
echo "✅ Vaultwarden is up."

# Run full account creation process
echo "[INFO] Running account creation script..."
python3 "${SCRIPT_DIR}/create_accounts.py"
if [ $? -eq 0 ]; then
    echo "✅ Account creation completed successfully."
else
    echo "❌ Account creation failed."
fi

echo === FINISHED setup.sh ===