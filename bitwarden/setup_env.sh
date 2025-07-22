#!/bin/bash
set -e

log_info "Checking if Bitwarden app is installed on the emulator..."
# The package name should match the one used in setup_app.sh
local pkg_name="com.x8bit.bitwarden.dev"
if adb shell pm list packages | grep -q "$pkg_name"; then
    log_success "Bitwarden app is already installed on the emulator."
else
    log_info "Bitwarden app not found. Running setup_app.sh to install and launch it..."
    "${SCRIPT_DIR}/setup_app.sh"
    log_success "Bitwarden app installed and launched."
fi

# Generate accounts
echo "Generating uuids..."
python generate_accounts.py

# Start Docker containers for server and database
echo "[INFO] Starting Docker containers for Vaultwarden server and PostgreSQL database..."
docker-compose up --build -d
echo "[INFO] Docker containers started."

# Wait for Vaultwarden to be ready (not just Postgres)
echo "[INFO] Waiting for Vaultwarden to be ready on http://localhost:8080..."
until curl -sf http://localhost:8080 > /dev/null; do
  sleep 2
done
echo "[INFO] Vaultwarden is up."

# Populate the database with seed data
echo "[INFO] Populating the database with seed data..."
docker-compose exec -T db psql -U bitwarden -d vaultwarden -f /seed/accounts.sql
docker-compose exec -T db psql -U bitwarden -d vaultwarden -f /seed/seed.sql
echo "[INFO] Database seeded."

# Dump the database to a file after setup
echo "[INFO] Dumping the database to db_dump.sql..."
docker-compose exec -T db pg_dump -U bitwarden -d vaultwarden > db_dump.sql
echo "[INFO] Database dump complete: db_dump.sql"