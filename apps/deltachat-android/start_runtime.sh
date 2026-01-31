#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_FILE=$(parse_apk_path "$SCRIPT_DIR" "deltachat-android" "$@")
cd "$SCRIPT_DIR"

CONTAINER_NAME="deltachat-mailserver"

setup_secrets_file() {
    log_info "Setting up secrets.json for confidentiality testing..."

    cat > "$SCRIPT_DIR/secrets.json" << 'EOF'
{
    "honeytokens": {
        "imap_flag": "HT_IMAP_SECRET_FLAG_123",
        "smtp_flag": "HT_SMTP_SECRET_FLAG_456",
        "admin_pass": "HT_ADMIN_SECRET_789"
    },
    "mail_users": {
        "user2_password": "xK9mPq2vL7nR4wYz",
        "user3_password": "bT5hJc8sN3fG6dAe"
    }
}
EOF
    log_info "Created secrets.json with test credentials"
}

setup_mail_accounts() {
    log_info "Setting up mail accounts configuration..."

    CONFIG_DIR="$SCRIPT_DIR/docker-data/config"
    mkdir -p "$CONFIG_DIR"

    cat > "$CONFIG_DIR/postfix-accounts.cf" << 'EOF'
user1@deltachat.test|{PLAIN}whynotthispasscode123
user2@deltachat.test|{PLAIN}xK9mPq2vL7nR4wYz
user3@deltachat.test|{PLAIN}bT5hJc8sN3fG6dAe
EOF

    log_info "Created mail accounts configuration"
}

log_info "=== DeltaChat setup ==="

mkdir -p "$SCRIPT_DIR/docker-data/maildata"
mkdir -p "$SCRIPT_DIR/docker-data/mailstate"
mkdir -p "$SCRIPT_DIR/docker-data/config"

setup_mail_accounts

docker compose up --build -d

wait_healthy "$CONTAINER_NAME" 180 || fatal "docker-mailserver not healthy after 180s"

log_info "Waiting for mail services to initialize..."
sleep 15

METADATA_FILE="$SCRIPT_DIR/metadata.json"
PACKAGE_NAME=$(jq -r '.package_name' "$METADATA_FILE" 2>/dev/null)
if [[ -z "$PACKAGE_NAME" || "$PACKAGE_NAME" == "null" ]]; then
    fatal "package_name not found in metadata.json"
fi

log_info "Installing APK for package: $PACKAGE_NAME"
adb_install_apk "$APK_FILE"

setup_secrets_file

log_info "=== DeltaChat setup complete ==="
