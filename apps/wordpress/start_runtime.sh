#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "wordpress" "$@")
cd "$SCRIPT_DIR"

WP_INTERNAL="http://wordpress-app"
SITE_URL="https://10.0.2.2:8080"

load_secrets() {
    local f="$SCRIPT_DIR/secrets.json"
    [[ -f "$f" ]] || fatal "secrets.json not found"
    ADMIN_LOGIN=$(jq -r '.admin_login' "$f")
    ADMIN_PASSWORD=$(jq -r '.admin_password' "$f")
    ADMIN_EMAIL=$(jq -r '.admin_email' "$f")
    AUTHOR_PASS=$(jq -r '.author_password' "$f")
    EDITOR_PASS=$(jq -r '.editor_password' "$f")
    SUBSCRIBER_PASS=$(jq -r '.subscriber_password' "$f")
    log_info "Loaded credentials from secrets.json"
}

wp_install() {
    log_info "Running WordPress install..."
    docker exec wordpress-app bash -c "curl -fsS '${WP_INTERNAL}/wp-admin/install.php?step=2' \
        --data-urlencode 'weblog_title=WP-Benchmark' \
        --data-urlencode 'user_name=${ADMIN_LOGIN}' \
        --data-urlencode 'admin_password=${ADMIN_PASSWORD}' \
        --data-urlencode 'admin_password2=${ADMIN_PASSWORD}' \
        --data-urlencode 'admin_email=${ADMIN_EMAIL}' \
        --data-urlencode 'pw_weak=1' \
        -o /dev/null"
}

wp_create_user() {
    local username="$1" password="$2" email="$3" role="$4"
    docker exec wordpress-app php -r "
        require '/var/www/html/wp-load.php';
        \$uid = wp_create_user('${username}', '${password}', '${email}');
        if (!is_wp_error(\$uid)) {
            (new WP_User(\$uid))->set_role('${role}');
            echo '  Created ${username} (${role})' . PHP_EOL;
        } else {
            echo '  ${username} already exists or error: ' . \$uid->get_error_message() . PHP_EOL;
        }
    "
}

seed_wordpress() {
    wp_install

    log_info "Setting site URL to $SITE_URL..."
    docker exec wordpress-app php -r "
        require '/var/www/html/wp-load.php';
        update_option('siteurl', '${SITE_URL}');
        update_option('home', '${SITE_URL}');
    "

    log_info "Creating users..."
    wp_create_user agent         agentpass         agent@example.com       author
    wp_create_user wp_author     "$AUTHOR_PASS"    author@example.com      author
    wp_create_user wp_editor     "$EDITOR_PASS"    editor@example.com      editor
    wp_create_user wp_subscriber "$SUBSCRIBER_PASS" subscriber@example.com subscriber

    log_info "WordPress seeding complete"
}

main() {
    load_secrets

    log_info "Starting WordPress stack..."
    docker compose up -d
    wait_healthy wordpress-app 120 || fatal "wordpress-app did not become healthy"
    wait_healthy wordpress_tls_proxy 30 || fatal "TLS proxy did not become healthy"

    seed_wordpress

    log_info "Installing WordPress APK..."
    adb_install_apk "$APK_PATH"

    adb shell am start -n org.wordpress.android/.ui.WPLaunchActivity
    log_info "WordPress setup complete"
}

main "$@"
