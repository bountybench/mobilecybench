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
    ./generate_ssl.sh
}


configure_mail_server() {
    echo "Configuring mail server users..."
    
    local usera_email=$(jq -r .username metadata.json)
    local usera_pw=$(jq -r .password metadata.json)
    local userb_pw=$(jq -r .userb_password secrets.json)

    # Create password hashes
    : > dms-config/postfix-accounts.cf
    local hash_usera=$(docker run --rm mailserver/docker-mailserver:15.1.0 bash -lc "doveadm pw -s SHA512-CRYPT -p '$usera_pw'")
    local hash_userb=$(docker run --rm mailserver/docker-mailserver:15.1.0 bash -lc "doveadm pw -s SHA512-CRYPT -p '$userb_pw'")
    
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

 
install_thunderbird() {
    echo "Installing Thunderbird APK..."
    
    # Validate APK directory exists
    if [ ! -d "apk" ]; then
        echo "ERROR: apk/ directory does not exist"
        exit 1
    fi

    # Check for APK files
    local apk_count=$(find apk -maxdepth 1 -name "*.apk" -type f 2>/dev/null | wc -l)
    if [ "$apk_count" -eq 0 ]; then
        echo "ERROR: No APK found in apk/ directory"
        exit 1
    fi

    # Locate APK file
    local apk_path=$(find apk -maxdepth 1 -name "*.apk" -type f 2>/dev/null | head -n 1)
    if [ -z "$apk_path" ]; then
        echo "ERROR: Failed to locate APK file"
        exit 1
    fi

    # Uninstall existing package if present
    local package_name=$(jq -r '.package_name' metadata.json)
    adb wait-for-device
    adb uninstall "$package_name" 2>/dev/null || echo "No existing installation found"

    # Install APK
    adb install -r -g "$apk_path"
    echo "Thunderbird installed successfully"
}

 
main() {
    install_dependencies
    generate_certificates
    configure_mail_server
    setup_backend
    install_thunderbird
    
    echo "Setup complete."
}

main "$@"
