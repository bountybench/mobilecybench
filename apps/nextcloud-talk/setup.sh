cd docker-setup
docker compose up --build -d
sleep 10
cd ..

python3 -m venv ./venv
source venv/bin/activate
pip install -r requirements.txt

cd app-setup
python regenerate_flags.py
cd ../test-ciaa
python common_setup.py
cd ../app-setup
python server_setup.py

sleep 10

docker exec -u root nextcloud-server chown -R www-data:www-data /var/www/html/config

docker exec -it nextcloud-server php -r '
    include "/var/www/html/config/config.php";
    $CONFIG["trusted_domains"][] = "10.0.2.2:8080";
    file_put_contents("/var/www/html/config/config.php", "<?php\n\$CONFIG = " . var_export($CONFIG, true) . ";\n");
'

chmod +x setup_app_source.sh
./setup_app_source.sh