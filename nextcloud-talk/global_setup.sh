# #!/bin/bash
# cd docker-setup
# docker-compose down -v 
# docker-compose up --build -d

# docker exec -it nextcloud-server chown -R www-data:www-data /var/www/html/config

# cd ..
# cd emulator-setup
# chmod 755 *.sh
# ./setup-jdk.sh
# ./start_emulator.sh

# docker exec -it kali-container bash "adb connect host.docker.internal:5555"

# docker exec -it nextcloud-server php -r '
#   include "/var/www/html/config/config.php";
#   $CONFIG["trusted_domains"][] = "10.0.2.2:8080";
#   file_put_contents("/var/www/html/config/config.php", "<?php\n\$CONFIG = " . var_export($CONFIG, true) . ";\n");
# 's

# cd ..
# source venv/bin/activate
# cd app-setup
# python server_setup.py
# chmod 755 *.sh
# ./emulator_connection.sh

# python verify_flags.py