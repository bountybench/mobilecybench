#!/bin/bash
set -e
 
pip install uiautomator2   

echo "Generating secrets..."
python seed/generate_secrets.py

echo "Starting docker-mailserver..."
docker compose up -d
 

# echo "Adding email accounts..." 
# docker exec thunderbird-mail setup email add "$USERNAME" "$PASSWORD" 
# docker exec thunderbird-mail setup email add "alex@test.com" "alexpass"
# docker exec thunderbird-mail setup email add "bob@test.com" "bobpass"

# docker logs cd84678a4d68a453cd2e6a3a4f1706bc3e9add597abd66b82ae700f9a6fbaf83

echo "Setting up app (APK link flow)..."
./setup_app_apklink.sh

echo "Done."
