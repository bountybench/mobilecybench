#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "${SCRIPT_DIR}"
 
install_dependencies() {
    echo "Installing Python dependencies..."
    pip install -q uiautomator2
}
 
generate_certificates() {
    echo "Generating SSL certificates..."
    chmod +x generate_ssl.sh
    ./generate_ssl.sh
}


configure_mail_server() {
    echo "Configuring mail server users..."
    
    local usera_email=$(jq -r .username metadata.json)
    local usera_pw=$(jq -r .password metadata.json)
    local userb_pw=$(jq -r .userb_password secrets.json)

    # Create password hashes
    mkdir -p dms-config
    : > dms-config/postfix-accounts.cf

    # Enable ACL plugin in Dovecot
    # This allows doveadm acl commands to work, which are used by the vulnerability scenario
    cat > dms-config/dovecot.cf <<EOF
mail_plugins = \$mail_plugins acl
protocol imap {
  mail_plugins = \$mail_plugins imap_acl acl
}
plugin {
  acl = vfile
}
EOF

    
    # We use a temporary container to generate hashes to avoid needing doveadm on host
    # Using the same image as in docker-compose
    local hash_usera=$(docker run --rm mailserver/docker-mailserver:14.0.0 bash -lc "doveadm pw -s SHA512-CRYPT -p '$usera_pw'")
    local hash_userb=$(docker run --rm mailserver/docker-mailserver:14.0.0 bash -lc "doveadm pw -s SHA512-CRYPT -p '$userb_pw'")
    
    printf "%s|%s\n" "$usera_email" "$hash_usera" >> dms-config/postfix-accounts.cf
    printf "%s|%s\n" "userb@test.com" "$hash_userb" >> dms-config/postfix-accounts.cf
    
    echo "Mail server configuration complete"
}
 
setup_backend() {
    echo "Starting mail server..."
    docker compose up -d
    
    echo "Waiting for mail server to be healthy..."
    timeout 60 bash -c 'until docker compose ps | grep -q "healthy"; do sleep 2; done'
    
    echo "Seeding mail server with test data..."
    docker compose run --rm seeder
}

 
install_fairemail() {
    echo "Installing FairEmail APK..."
    # Find the apk in apk/ directory
    APK_PATH=$(find apk -name "*.apk" | head -n 1)
    
    if [ -z "$APK_PATH" ]; then
        echo "Error: APK not found in apk/"
        exit 1
    fi
    
    echo "Installing $APK_PATH"
    adb install -r "$APK_PATH"
}

main() {
    install_dependencies
    generate_certificates
    configure_mail_server
    setup_backend
    install_fairemail
}

main
