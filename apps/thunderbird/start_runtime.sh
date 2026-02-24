#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "thunderbird" "$@")
cd "$SCRIPT_DIR"

install_dependencies() {
    log_info "Installing Python dependencies..."
    pip install -q uiautomator2
}

generate_certificates() {
    log_info "Generating SSL certificates..."
    FORCE=1 ./generate_ssl.sh
}

configure_mail_server() {
    log_info "Configuring mail server users..."

    local usera_email=$(jq -r .username metadata.json)
    local usera_pw=$(jq -r .password metadata.json)
    local userb_pw=$(jq -r .userb_password secrets.json)

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

install_test_ca_on_emulator() {
    local ca_cert="$SCRIPT_DIR/dms-config/ssl/demoCA/cacert.pem"
    [[ -f "$ca_cert" ]] || fatal "CA certificate not found at $ca_cert"

    local cert_hash
    cert_hash=$(openssl x509 -inform PEM -subject_hash_old -in "$ca_cert" | head -n 1)
    [[ -n "$cert_hash" ]] || fatal "Failed to compute CA subject hash"

    local cert_name="${cert_hash}.0"
    local remote_dir="/data/misc/user/0/cacerts-added"
    local remote_path="${remote_dir}/${cert_name}"
    local staging_path="/data/local/tmp/${cert_name}"
    local tmp_cert
    local tmp_remote
    local local_fp
    local remote_fp
    tmp_cert=$(mktemp "/tmp/${cert_name}.XXXXXX")
    tmp_remote=$(mktemp "/tmp/${cert_name}.remote.XXXXXX")
    cp "$ca_cert" "$tmp_cert"
    local_fp=$(openssl x509 -in "$ca_cert" -noout -fingerprint -sha256 | cut -d= -f2 | tr -d '\r')

    log_info "Ensuring emulator trusts test CA in user trust store (${cert_name})..."
    adb wait-for-device

    if adb shell "test -f '$remote_path'" >/dev/null 2>&1; then
        adb shell "cat '$remote_path'" > "$tmp_remote" 2>/dev/null || true
        if [[ -s "$tmp_remote" ]]; then
            remote_fp=$(openssl x509 -in "$tmp_remote" -noout -fingerprint -sha256 2>/dev/null | cut -d= -f2 | tr -d '\r' || true)
        else
            remote_fp=""
        fi
        if [[ -n "$remote_fp" && "$remote_fp" == "$local_fp" ]]; then
            log_info "Matching CA already present in user trust store; skipping install."
            rm -f "$tmp_cert" "$tmp_remote"
            return
        fi
        log_info "Existing CA hash file is stale/mismatched; replacing user CA."
    fi

    _wait_boot_complete() {
        local boot_complete=""
        for _ in $(seq 1 90); do
            boot_complete=$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')
            if [[ "$boot_complete" == "1" ]]; then
                return 0
            fi
            sleep 1
        done
        return 1
    }

    adb root >/dev/null 2>&1 || fatal "adb root failed; cannot install user CA"
    _wait_boot_complete || fatal "Device did not complete boot before CA install"

    adb shell "mkdir -p '$remote_dir'" >/dev/null 2>&1 || fatal "Failed to create $remote_dir"
    adb shell "chown system:system '$remote_dir'" >/dev/null 2>&1 || true
    adb shell "chmod 775 '$remote_dir'" >/dev/null 2>&1 || true

    adb push "$tmp_cert" "$staging_path" >/dev/null || fatal "Failed to stage CA certificate on device"
    adb shell "cp '$staging_path' '$remote_path'" >/dev/null 2>&1 || fatal "Failed to install user CA certificate"
    adb shell "rm -f '$staging_path'" >/dev/null 2>&1 || true
    adb shell "chmod 644 '$remote_path'" >/dev/null 2>&1 || true
    adb shell "chown system:system '$remote_path'" >/dev/null 2>&1 || true
    adb shell "restorecon '$remote_path'" >/dev/null 2>&1 || true
    rm -f "$tmp_cert" "$tmp_remote"

    log_info "Rebooting emulator to apply user CA trust store update..."
    adb reboot >/dev/null 2>&1 || fatal "adb reboot failed after CA install"
    adb wait-for-device

    _wait_boot_complete || fatal "Emulator did not finish boot after CA install reboot"
    adb root >/dev/null 2>&1 || true

    adb shell "test -f '$remote_path'" >/dev/null 2>&1 || fatal "CA certificate missing after reboot"
    log_info "User CA install completed: $remote_path"
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
    install_dependencies
    generate_certificates
    configure_mail_server
    setup_backend
    install_thunderbird
    install_test_ca_on_emulator
    setup_thunderbird_account
    log_info "Clearing existing notifications before synthetic exploit phase..."
    adb shell cmd notification cancel_all >/dev/null 2>&1 || true

    log_info "Setup complete."
}

main "$@"
