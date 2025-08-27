#!/bin/bash
set -e

#! all the documentation for how I set it up is from here: https://jitsi.github.io/handbook/docs/devops-guide/devops-guide-docker

echo "Downloading latest Jitsi Docker setup..."
LATEST_ZIP_URL=$(curl -s https://api.github.com/repos/jitsi/docker-jitsi-meet/releases/latest | grep 'zip' | cut -d\" -f4)
wget "$LATEST_ZIP_URL" -O jitsi-docker-latest.zip

echo "Extracting Docker setup..."
unzip jitsi-docker-latest.zip -d jitsi-docker

echo "Heading into the Jitsi Docker directory..."
cd jitsi-docker

echo "Copying env.example from Jitsi Docker setup to .env"
cp env.example .env

echo "Generating strong passwords..."
bash gen-passwords.sh

echo "Creating configuration directories..."
mkdir -p ~/.jitsi-meet-cfg/{web,transcripts,prosody/config,prosody/prosody-plugins-custom,jicofo,jvb,jigasi,jibri}

echo "Starting Jitsi Meet containers via Docker Compose..."
docker compose up -d

echo "Setup complete! Ready to test Jitsi Meet. (https://localhost:8443/)"
