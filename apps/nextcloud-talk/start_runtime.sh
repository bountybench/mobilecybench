#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "nextcloud-talk" "$@")
cd "$SCRIPT_DIR"

docker compose up --build -d
sleep 20

python3 -m venv ./venv
source venv/bin/activate
pip install -r requirements.txt

python server_setup.py

sleep 10

if docker exec nextcloud-server test -f /var/www/html/config/config.php; then
    docker exec -u root nextcloud-server chown -R www-data:www-data /var/www/html/config

    docker exec -i nextcloud-server php -r '
        include "/var/www/html/config/config.php";
        if (!isset($CONFIG["trusted_domains"])) {
            $CONFIG["trusted_domains"] = array();
        } elseif (!is_array($CONFIG["trusted_domains"])) {
            $CONFIG["trusted_domains"] = array($CONFIG["trusted_domains"]);
        }
        if (!in_array("10.0.2.2:8080", $CONFIG["trusted_domains"])) {
            $CONFIG["trusted_domains"][] = "10.0.2.2:8080";
        }
        $config_content = "<?php\n\$CONFIG = " . var_export($CONFIG, true) . ";\n";
        file_put_contents("/var/www/html/config/config.php", $config_content);
    '
else
    log_warn "Config not ready yet; skipping trusted_domains update."
fi

log_info "Installing Nextcloud Talk APK..."
adb_install_apk "$APK_PATH"
log_info "Nextcloud Talk installed successfully!"
