#!/bin/bash
set -e

BITWARDEN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MOBILECYBENCH_ROOT="$(cd "$BITWARDEN_DIR/../.." && pwd)"
PKG_NAME="com.x8bit.bitwarden.dev"

export UI_TARGET_PACKAGE="$PKG_NAME"

echo === RUNNING setup.sh ===

# Check if Bitwarden is installed on the emulator
echo "[DEBUG] Checking if Bitwarden app is installed on the emulator..."
if adb shell pm list packages | grep -q "$PKG_NAME"; then
  echo "[DEBUG] Bitwarden app is already installed. Skipping build."
else
  echo "[DEBUG] Bitwarden app not found. Running setup_app_source.sh to build APK..."
  "${BITWARDEN_DIR}/setup_app_source.sh"
fi

# Run setup_app.sh to install Bitwarden app
echo "[INFO] Running setup_app.sh to install Bitwarden app..."
"${BITWARDEN_DIR}/setup_app.sh"
echo "[INFO] Bitwarden app installed."


# Start Docker containers for server and database
echo "[INFO] Starting Docker containers for Vaultwarden server and PostgreSQL database..."
docker compose -f "$BITWARDEN_DIR/docker-compose.yml" up --build -d
echo "[INFO] Docker containers started."

# Wait for Vaultwarden to be ready (not just Postgres)
echo "[INFO] Waiting for Vaultwarden to be ready on http://localhost:8000..."
until curl -sf http://localhost:8000 > /dev/null; do
  sleep 2
done
echo "[INFO] Vaultwarden is up."

# Run full account creation process
echo "[INFO] Running account creation script with python3..."
cd "$MOBILECYBENCH_ROOT"
python3 -m apps.bitwarden.create_accounts
if [ $? -eq 0 ]; then
  echo "[INFO] Account creation completed successfully."
else
  echo "[ERROR] Account creation failed."
fi

echo === FINISHED setup.sh ===