#!/bin/bash

cd docker-setup
docker-compose down -v 
docker-compose up --build -d

docker exec -it nextcloud-server php -r '
  include "/var/www/html/config/config.php";
  $CONFIG["trusted_domains"][] = "10.0.2.2:8080";
  file_put_contents("/var/www/html/config/config.php", "<?php\n\$CONFIG = " . var_export($CONFIG, true) . ";\n");
'

cd ..
cd emulator-setup
./setup-jdk.sh
./start_emulator.sh

cd ..
source venv/bin/activate
cd app-setup
python server_setup.py
./emulator_connection.sh
python verify_flags.py
