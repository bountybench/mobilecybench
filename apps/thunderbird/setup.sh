#!/bin/bash
set -e
 
pip install -q uiautomator2   

echo "Generating uuid..."
python generate_uuid.py

echo "Generating ssl..."
./generate_ssl.sh
 
echo -n > dms-config/postfix-accounts.cf 



USERA_EMAIL=$(jq -r .username metadata.json)
USERA_PW=$(jq -r .password metadata.json)
USERB_PW=$(jq -r .userb_password secrets.json) 


# Pre-seed accounts file with users so docker-mailserver doesn't complain
echo "Seeding dms-config/postfix-accounts.cf..."
: > dms-config/postfix-accounts.cf
HASH_USERA=$(docker run --rm mailserver/docker-mailserver:15.1.0 bash -lc "doveadm pw -s SHA512-CRYPT -p '$USERA_PW'")
HASH_USERB=$(docker run --rm mailserver/docker-mailserver:15.1.0 bash -lc "doveadm pw -s SHA512-CRYPT -p '$USERB_PW'")
printf "%s|%s\n" "$USERA_EMAIL" "$HASH_USERA" >> dms-config/postfix-accounts.cf
printf "%s|%s\n" "userb@test.com" "$HASH_USERB" >> dms-config/postfix-accounts.cf


echo "Starting docker-mailserver..."
docker compose up -d
# docker exec -it thunderbird-mail setup email add "$USERA_EMAIL" "$USERA_PW" || true
# docker exec -it thunderbird-mail setup email add userb@test.com "$USERB_PW" || true 


echo "Attempting to install using pre-built APK..."
chmod u+x setup_app_apklink.sh
./setup_app_apklink.sh
# chmod u+x setup_app_source.sh
# ./setup_app_source.sh
echo "Done."
