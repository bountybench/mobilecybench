#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "nextcloud-talk" "$@")
cd "$SCRIPT_DIR"

TRUSTED_DOMAIN="$(python3 - <<'PY'
from common_setup import get_trusted_domain
print(get_trusted_domain())
PY
)"

docker compose up --build -d
wait_healthy "nextcloud-talk-tls-proxy" 180 || fatal "nextcloud-talk-tls-proxy did not become healthy"

python3 server_setup.py

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
        if (!in_array("'"${TRUSTED_DOMAIN}"'", $CONFIG["trusted_domains"])) {
            $CONFIG["trusted_domains"][] = "'"${TRUSTED_DOMAIN}"'";
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
