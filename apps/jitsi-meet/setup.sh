#!/bin/bash

#! all the documentation for how I set it up is from here: https://jitsi.github.io/handbook/docs/devops-guide/devops-guide-docker

echo "Downloading latest Jitsi Docker setup..."
LATEST_ZIP_URL=$(curl -s https://api.github.com/repos/jitsi/docker-jitsi-meet/releases/latest | grep 'zip' | cut -d\" -f4)
wget "$LATEST_ZIP_URL" -O jitsi-docker-latest.zip

echo "Extracting Docker setup..."
unzip jitsi-docker-latest.zip -d jitsi-docker

echo "Heading into the Jitsi Docker directory..."
cd jitsi-docker
cd $(ls -d */ | head -n 1) #cd into nested folder

echo "Copying env.example from Jitsi Docker setup to .env"
cp env.example .env

echo "Generating strong passwords..."
bash gen-passwords.sh

echo "Creating configuration directories..."
mkdir -p ~/.jitsi-meet-cfg/{web,transcripts,prosody/config,prosody/prosody-plugins-custom,jicofo,jvb,jigasi,jibri}

echo "Creating jitsi-network"
docker network create jitsi-network

echo "Starting Jitsi Meet containers via Docker Compose..."
docker compose up -d

echo "Connecting containers to jitsi-network"
for container in $(docker ps -q); do
    docker network connect jitsi-network $container 2>/dev/null || true
done

echo "Updating the Jitsi Meet config url"
docker-compose exec web bash -c "sed -i 's|https://localhost:8443|https://jitsi-meet:8443|' /config/config.js"

echo "Setup complete! Ready to test Jitsi Meet. (https://jitsi-meet:8443)"
