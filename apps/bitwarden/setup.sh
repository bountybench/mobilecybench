#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_NAME="com.x8bit.bitwarden"

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

echo === RUNNING setup.sh ===

# Detect CI environment
is_github_ci() {
    [[ -n "$GITHUB_ACTIONS" ]] || [[ -n "$CI" ]] || [[ -n "$GITHUB_RUN_ID" ]]
}

# Check if Bitwarden app is installed on the emulator
log_info "Checking if Bitwarden app is installed on the emulator..."
if adb shell pm list packages | grep -q "$PKG_NAME"; then
    log_success "Bitwarden app is already installed on the emulator."
else
    log_info "Bitwarden app not found."
    # In CI, always run setup_app_apk.sh to ensure fresh installation
    if is_github_ci; then
        log_info "Running in GitHub CI"
        log_info "Running setup_app_apk.sh to install and launch it..."
        "${SCRIPT_DIR}/setup_app_apk.sh"
        log_success "Bitwarden app reinstalled and launched for CI."
    else
        log_info "Running setup_app_source.sh to install and launch it..."
        "${SCRIPT_DIR}/setup_app_source.sh"
        log_success "Bitwarden app installed and launched."
    fi
fi

# Start Docker containers for server and database
log_info "Starting Docker containers for Vaultwarden server and PostgreSQL database..."
docker compose up --build -d
log_success "Docker containers started."

# Wait for Vaultwarden to be ready (not just Postgres)
log_info "Waiting for Vaultwarden to be ready on http://localhost:8000..."
until curl -sf http://localhost:8000 > /dev/null; do
  sleep 2
done
log_success "Vaultwarden is up."

# Run full account creation process
log_info "Running account creation script..."
python3 "${SCRIPT_DIR}/create_accounts.py"
if [ $? -eq 0 ]; then
    log_success "Account creation completed successfully."
else
    log_error "Account creation failed."
fi

echo === FINISHED setup.sh ===