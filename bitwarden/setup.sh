#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
set -e

# Parse command line arguments
FAST_MODE=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --fast)
            FAST_MODE=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--fast]"
            exit 1
            ;;
    esac
done

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

# Ensure port 8080 is free before starting Docker
log_info "Checking if port 8080 is in use and shutting down any conflicting processes..."
if lsof -i :8080 -sTCP:LISTEN -t >/dev/null; then
    lsof -i :8080 -sTCP:LISTEN -t | xargs kill -9 || true
    log_success "Closed processes on port 8080."
else
    log_info "No process found on port 8080. Port is clear."
fi

# Set up ADB reverse port forwarding for emulator connectivity
setup_adb_reverse() {
    log_info "Setting up ADB reverse for port 8080 (host <-> emulator)..."
    adb reverse tcp:8080 tcp:8080 || true
    log_success "ADB reverse for port 8080 set."
}

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

if [ "$FAST_MODE" = true ]; then
    # Fast mode: populate database using existing dump.sql
    log_info "Fast mode enabled. Populating database using dump.sql..."
    
    if [ ! -f "${SCRIPT_DIR}/dump.sql" ]; then
        log_error "dump.sql not found. Cannot run in fast mode."
    fi
    
    log_info "Restoring database from dump.sql..."
    docker exec -i bitwarden-db-1 psql -U bitwarden -d vaultwarden < "${SCRIPT_DIR}/dump.sql"
    if [ $? -eq 0 ]; then
        log_success "Database restored from dump.sql successfully."
    else
        log_error "Failed to restore database from dump.sql."
    fi
else
    # Normal mode: run full account creation process
    log_info "Running account creation script..."
    python3 "${SCRIPT_DIR}/create_accounts_ui.py"
    if [ $? -eq 0 ]; then
        log_success "Account creation completed successfully."
    else
        log_error "Account creation failed."
    fi
fi

# Run the secrets extraction script
log_info "Running secrets extraction script..."
python3 "${SCRIPT_DIR}/create_secrets_from_dump.py"
if [ $? -eq 0 ]; then
    log_success "Secrets extraction completed successfully."
else
    log_error "Secrets extraction failed."
fi

echo === FINISHED setup_env.sh ===