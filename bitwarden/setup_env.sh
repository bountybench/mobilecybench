#!/bin/bash
set -e

log_info() {
    echo "[INFO] $1"
}

log_success() {
    echo "✅ $1"
}

log_error() {
    echo "❌ [ERROR] $1" >&2
    exit 1
}

echo === RUNNING setup_env.sh ===

log_info "Checking if Bitwarden app is installed on the emulator..."
# The package name should match the one used in setup_app.sh
pkg_name="com.x8bit.bitwarden.dev"
if adb shell pm list packages | grep -q "$pkg_name"; then
    log_success "Bitwarden app is already installed on the emulator."
else
    log_info "Bitwarden app not found. Running setup_app.sh to install and launch it..."
    "${SCRIPT_DIR}/setup_app.sh"
    log_success "Bitwarden app installed and launched."
fi

# Set up ADB reverse port forwarding for emulator connectivity
setup_adb_reverse() {
    log_info "Setting up ADB reverse for port 8080 (host <-> emulator)..."
    adb reverse tcp:8080 tcp:8080 || true
    log_success "ADB reverse for port 8080 set."
}

# Generate accounts
# NEW, CORRECTED CODE in setup_env.sh
log_info "Generating uuids..."
# Export the variable so the Python script can read it
export PASSWORD_ITERATIONS=600000
python generate_accounts.py
log_success "uuids generated."

# Start Docker containers for server and database
log_info "Starting Docker containers for Vaultwarden server and PostgreSQL database..."
docker-compose up --build -d
log_success "Docker containers started."

# Always set up ADB reverse port forwarding for port 8080
log_info "Ensuring ADB reverse port forwarding for port 8080 is active..."
adb reverse tcp:8080 tcp:8080 || true
log_success "ADB reverse for port 8080 is set."

# Wait for Vaultwarden to be ready (not just Postgres)
log_info "Waiting for Vaultwarden to be ready on http://localhost:8080..."
until curl -sf http://localhost:8080 > /dev/null; do
  sleep 2
done
log_success "Vaultwarden is up."

# Ensure database is clean before seeding
log_info "Ensuring database is clean before seeding..."
docker-compose exec -T db psql -U bitwarden -d vaultwarden -c "TRUNCATE TABLE users, ciphers, devices, auth_requests, twofactor, twofactor_incomplete, twofactor_duo_ctx, favorites, folders, folders_ciphers, collections, collections_groups, ciphers_collections, users_collections, users_organizations, organizations, groups, groups_users, emergency_access, invitations, sends, attachments, event, org_policies, organization_api_key CASCADE;" || true
log_success "Database cleaned."

# Populate the database with seed data
log_info "Populating the database with seed data..."
docker-compose exec -T db psql -U bitwarden -d vaultwarden -f /seed/seed.sql
log_success "Database seeded."

# Dump the database to a file after setup
log_info "Dumping the database to db_dump.sql..."
docker-compose exec -T db pg_dump -U bitwarden -d vaultwarden > db_dump.sql
log_success "Database dump complete: db_dump.sql"

echo === FINISHED setup_env.sh ===