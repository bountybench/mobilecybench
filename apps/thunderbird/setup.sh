#!/bin/bash
set -e
 
pip install uiautomator2   

echo "Generating uuid..."
python generate_uuid.py

echo "Starting docker-mailserver..."
docker compose up -d
 

# echo "Adding email accounts..." 
echo -n > dms-config/postfix-accounts.cf 

USERA_EMAIL=$(jq -r .username metadata.json)
USERA_PW=$(jq -r .password metadata.json)
USERB_PW=$(jq -r .userb_password secrets.json) 

docker exec -it thunderbird-mail setup email add "$USERA_EMAIL" "$USERA_PW" || true
docker exec -it thunderbird-mail setup email add userb@test.com "$USERB_PW" || true 
 

echo "Attempting to install using pre-built APK..."
# chmod u+x setup_app_apklink.sh
# ./setup_app_apklink.sh
chmod u+x setup_app_source.sh
./setup_app_source.sh
echo "Done."
