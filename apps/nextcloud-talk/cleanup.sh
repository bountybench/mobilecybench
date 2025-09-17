cd docker-setup
docker compose down -v
rm -rf ./venv

cd ..
rm -f nextcloud-talk.apk

# Remove log files
rm -f *.log

# Remove scores and venv
rm -f scores.json
