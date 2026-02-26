#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "thunderbird" "$@")
cd "$SCRIPT_DIR"

generate_certificates() {
    log_info "Generating SSL certificates..."
    FORCE=1 ./generate_ssl.sh
}

configure_mail_server() {
    log_info "Configuring mail server users..."

    local usera_email=$(jq -r .username metadata.json)
    local usera_pw=$(jq -r .password metadata.json)
    local userb_pw=$(jq -r .userb_password secrets.json)
    mkdir -p dms-config

    : > dms-config/postfix-accounts.cf
    local hash_usera=$(docker run --rm mailserver/docker-mailserver:15.1.0 bash -lc "doveadm pw -s SHA512-CRYPT -p '$usera_pw'")
    local hash_userb=$(docker run --rm mailserver/docker-mailserver:15.1.0 bash -lc "doveadm pw -s SHA512-CRYPT -p '$userb_pw'")

    printf "%s|%s\n" "$usera_email" "$hash_usera" >> dms-config/postfix-accounts.cf
    printf "%s|%s\n" "userb@test.com" "$hash_userb" >> dms-config/postfix-accounts.cf

    log_info "Mail server configuration complete"
}

setup_backend() {
    log_info "Starting mail server..."
    docker_compose_up

    log_info "Waiting for mail server to be healthy..."
    container_id=$(docker compose ps -q thunderbird-app | head -n 1)
    if [[ -z "$container_id" ]]; then
        fatal "Failed to resolve thunderbird-app container ID"
    fi
    wait_healthy "$container_id" 60 || fatal "thunderbird-app container did not become healthy"

    log_info "Seeding mail server with test data..."
    docker compose run --rm seeder
}

setup_thunderbird_account() {
    log_info "Configuring Thunderbird account via UI automation..."

    local package_name usera_email usera_pw
    package_name=$(jq -r '.package_name' metadata.json)
    usera_email=$(jq -r '.username' metadata.json)
    usera_pw=$(jq -r '.password' metadata.json)

    TB_PKG="$package_name" \
    TB_ACCOUNT_EMAIL="$usera_email" \
    TB_ACCOUNT_PASSWORD="$usera_pw" \
    TB_IMAP_HOST="${TB_IMAP_HOST:-10.0.2.2}" \
    TB_IMAP_PORT="${TB_IMAP_PORT:-993}" \
    TB_SMTP_HOST="${TB_SMTP_HOST:-10.0.2.2}" \
    TB_SMTP_PORT="${TB_SMTP_PORT:-465}" \
    python3 "$SCRIPT_DIR/setup_account_ui.py" || fatal "Thunderbird UI account setup failed"

    log_info "Thunderbird account setup complete"
}

install_thunderbird() {
    log_info "Installing Thunderbird APK..."

    local apk_path="$APK_PATH"

    if [ -z "$apk_path" ]; then
        if [ ! -d "apk" ]; then
            fatal "apk/ directory does not exist"
        fi

        local apk_count=$(find apk -maxdepth 1 -name "*.apk" -type f 2>/dev/null | wc -l)
        if [ "$apk_count" -eq 0 ]; then
            fatal "No APK found in apk/ directory"
        fi

        apk_path=$(find apk -maxdepth 1 -name "*.apk" -type f 2>/dev/null | head -n 1)
        if [ -z "$apk_path" ]; then
            fatal "Failed to locate APK file"
        fi
    fi

    if [ ! -f "$apk_path" ]; then
        fatal "APK not found at $apk_path"
    fi

    local package_name=$(jq -r '.package_name' metadata.json)
    adb wait-for-device
    adb uninstall "$package_name" 2>/dev/null || echo "No existing installation found"

    adb_install_apk "$apk_path"
    log_info "Thunderbird installed successfully"
}

main() {
    generate_certificates
    configure_mail_server
    setup_backend
    install_thunderbird
    setup_thunderbird_account
    log_info "Clearing existing notifications before synthetic exploit phase..."
    adb shell cmd notification cancel_all >/dev/null 2>&1 || true

    log_info "Setup complete."
}

main "$@"
