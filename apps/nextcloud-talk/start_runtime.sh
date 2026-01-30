docker compose up --build -d
sleep 20

python3 -m venv ./venv
source venv/bin/activate
pip install -r requirements.txt

python server_setup.py

sleep 10

# Only proceed if Nextcloud has finished initial install and config exists
if docker exec nextcloud-server test -f /var/www/html/config/config.php; then
    docker exec -u root nextcloud-server chown -R www-data:www-data /var/www/html/config

    docker exec -it nextcloud-server php -r '
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
    echo "Config not ready yet; skipping trusted_domains update."
fi

install_nextcloud_talk() {
    echo "Installing Nextcloud Talk APK..."

    if ! adb devices | grep -q "device\|emulator"; then
        echo "ERROR: No Android emulator found."
        exit 1
    fi

    APK_PATH="apk/nextcloud-talk.apk"

    if [[ ! -f "$APK_PATH" ]]; then
        echo "ERROR: APK not found at $APK_PATH"
        echo "Please run setup_app_source.sh first to build and sign the APK."
        exit 1
    fi

    adb install -r "$APK_PATH" || { echo "Failed to install APK"; exit 1; }
    echo "Nextcloud Talk installed successfully!"
}

install_nextcloud_talk
