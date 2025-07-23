#!/bin/bash

set -e

# Test Harness for Bitwarden Database Seeding
# This script automates the entire process of generating secrets,
# seeding the database, and verifying the results.

# --- Configuration ---
set -e # Exit immediately if a command exits with a non-zero status.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB_CONTAINER_NAME="bitwarden_db_test"
DB_USER="bitwarden"
DB_NAME="vaultwarden"
export PGPASSWORD='super_strong_password' # Set for non-interactive psql

# --- Helper Functions ---
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

# --- Test Steps ---

# 1. Check Prerequisites and Clean Up Old Runs
check_prerequisites() {
    log_info "Checking for Docker and psql..."
    command -v docker >/dev/null 2>&1 || log_error "Docker is not installed. Please install Docker."
    command -v psql >/dev/null 2>&1 || log_error "psql is not installed. Please install PostgreSQL client tools."

    log_info "Cleaning up any previous test runs..."
    docker-compose down --volumes 2>/dev/null || true
}

# 2. Start Database Container
start_database() {
    log_info "Starting PostgreSQL container in detached mode..."
    docker-compose up --build -d db
    
    log_info "Waiting for database to be ready..."
    until docker-compose exec -T db pg_isready -U "$DB_USER" -d "$DB_NAME" -q; do
        sleep 2
    done
    log_success "Database is up and running."
}

# 2. Ensure Bitwarden App is Installed
ensure_app_installed() {
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
}

# 3. Launch App to Register Device and Learn UUID
learn_device_uuid() {
    log_info "Waiting for the app to register its device UUID in the database..."
    
    DEVICE_UUID=""
    RETRY_COUNT=0
    MAX_RETRIES=15

    until [ -n "$DEVICE_UUID" ]; do
        DEVICE_UUID=$(docker-compose exec -T db psql -U "$DB_USER" -d "$DB_NAME" -t -c "SELECT uuid FROM devices LIMIT 1;" | xargs)
        if [ -z "$DEVICE_UUID" ]; then
            RETRY_COUNT=$((RETRY_COUNT + 1))
            if [ "$RETRY_COUNT" -gt "$MAX_RETRIES" ]; then
                log_error "Device UUID not found in database after $MAX_RETRIES retries. App may not have launched or registered correctly."
            fi
            log_info "Device not yet registered. Retrying in 2 seconds... ($RETRY_COUNT/$MAX_RETRIES)"
            sleep 2
        fi
    done

    log_success "Learned Device UUID: $DEVICE_UUID"
    # The learned UUID will be passed to the next step
}


# 4. Generate Secrets and Seed File
generate_secrets() {
    # The first argument ($1) is the learned device UUID
    local device_uuid=$1
    if [ -z "$device_uuid" ]; then
        log_error "No device UUID provided to generate_secrets function."
    fi

    log_info "Running Python script to generate secrets with learned UUID: $device_uuid"
    python3 "${SCRIPT_DIR}/generate_secrets.py" --device-uuid "$device_uuid"
    log_success "secrets.sql, secrets.json, and logins.txt generated."
}

# 5. Run the Seeding Process
seed_database() {
    log_info "Seeding the database with generated secrets..."

    # Copy seed and secrets files into the container
    local container_id=$(docker-compose ps -q db)
    docker cp "${SCRIPT_DIR}/bitwarden-seed.sql" "$container_id":/tmp/bitwarden-seed.sql
    docker cp "${SCRIPT_DIR}/secrets.sql" "$container_id":/tmp/secrets.sql

    # Run psql inside the container, referencing the in-container path
    docker-compose exec -T db psql -U "$DB_USER" -d "$DB_NAME" -f /tmp/bitwarden-seed.sql

    log_success "Database seeded successfully."
}

# 6. Verify the Results
verify_seeding() {
    log_info "Verifying seeded data..."
    
    USER_COUNT=$(docker-compose exec -T db psql -U "$DB_USER" -d "$DB_NAME" -t -c "SELECT COUNT(*) FROM users;")
    CIPHER_COUNT=$(docker-compose exec -T db psql -U "$DB_USER" -d "$DB_NAME" -t -c "SELECT COUNT(*) FROM ciphers;")
    DEVICE_COUNT=$(docker-compose exec -T db psql -U "$DB_USER" -d "$DB_NAME" -t -c "SELECT COUNT(*) FROM devices;")

    # Trim whitespace from psql output
    USER_COUNT=$(echo "$USER_COUNT" | xargs)
    CIPHER_COUNT=$(echo "$CIPHER_COUNT" | xargs)
    DEVICE_COUNT=$(echo "$DEVICE_COUNT" | xargs)

    if [ "$USER_COUNT" -eq 3 ]; then
        log_success "Verification passed: Found 3 users in the database."
    else
        log_error "Verification failed: Expected 3 users, but found $USER_COUNT."
    fi

    if [ "$CIPHER_COUNT" -eq 15 ]; then
        log_success "Verification passed: Found 15 ciphers in the database."
    else
        log_error "Verification failed: Expected 15 ciphers, but found $CIPHER_COUNT."
    fi

    if [ "$DEVICE_COUNT" -eq 3 ]; then
        log_success "Verification passed: Found 3 devices in the database."
    else
        log_error "Verification failed: Expected 3 devices, but found $DEVICE_COUNT."
    fi
}

# 6. Clean Up Environment
cleanup() {
    log_info "Test run complete. Cleaning up Docker containers..."
    echo "Removing secret files..."
    # rm -f secrets.sql
    # rm -f secrets.json
    # rm -f logins.txt

    # Uninstall Bitwarden app and clear all its data from the emulator
    # local pkg_name="com.x8bit.bitwarden.dev"
    # log_info "Uninstalling Bitwarden app and clearing all local data from the emulator..."
    # adb uninstall "$pkg_name" || log_info "Bitwarden app was not installed or already removed."
    # Optionally, also clear data if app is still present (shouldn't be after uninstall, but for safety)
    # adb shell pm clear "$pkg_name" || true

    docker-compose down -v
    log_success "Environment is clean."
}


# --- Main Execution ---
main() {
    cd "$SCRIPT_DIR"
    
    trap cleanup EXIT # Ensure cleanup happens even on script failure

    check_prerequisites
    start_database
    
    # Ensure the app is installed and launched if needed
    ensure_app_installed
    
    # New workflow step
    learn_device_uuid
    local learned_uuid
    learned_uuid=$(learn_device_uuid)

    generate_secrets "$learned_uuid"
    seed_database
    verify_seeding

    log_info "--------------------------------------------------"
    log_success "Test Harness executed successfully!"
    log_info "You can find the generated user credentials in: ${SCRIPT_DIR}/logins.txt"
    log_info "--------------------------------------------------"

    # Dump the database for analysis
    log_info "Dumping the seeded database to bitwarden_db_dump.sql..."
    docker-compose exec -T db pg_dump -U "$DB_USER" -d "$DB_NAME" > "$SCRIPT_DIR/bitwarden_db_dump.sql"
    log_success "Database dump saved to: $SCRIPT_DIR/bitwarden_db_dump.sql"
}

main 