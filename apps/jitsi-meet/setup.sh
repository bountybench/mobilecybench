#!/bin/bash

#! all the documentation for how I set it up is from here: https://jitsi.github.io/handbook/docs/devops-guide/devops-guide-docker

#\\\DOCKER COMPOSING SECTION///
git submodule update --init jitsi-docker

echo "Docker setup already pre-extracted."
echo "Heading into the Jitsi Docker directory..."
cd jitsi-docker
cd jitsi-latest #cd into nested folder

echo "Copying env.example from Jitsi Docker setup to .env"
cp env.example .env

echo "Generating strong passwords..."
bash gen-passwords.sh

echo "Creating configuration directories..."
mkdir -p ~/.jitsi-meet-cfg/{web,transcripts,prosody/config,prosody/prosody-plugins-custom,jicofo,jvb,jigasi,jibri}

echo "Starting Jitsi Meet containers via Docker Compose..."
docker compose up -d

echo "Connecting containers to shared_net"
for container in $(docker ps -q); do
    docker network connect shared_net $container 2>/dev/null || true
done


echo "Setup complete! Ready to test Jitsi Meet. (http://localhost:8000)"

#\\\APK INSTALLATION SECTION///

install_jitsi() {
    echo "Installing Jitsi Meet on Android emulator..."

    # Check if emulator is running
    echo "Checking for Android emulator..."
    
    if ! adb devices | grep -q "emulator.*device"; then
        echo "Warning: No emulator detected. Skipping APK installation."
        echo "APK build completed successfully. Install manually if needed."
        return 1
    fi

    cd ../..
    cd codebase
    cd android
    APK_PATH="app/build/outputs/apk/debug/app-debug.apk"

    if [[ ! -f $APK_PATH ]]; then
        echo "ERROR: APK not found at $APK_PATH"
        echo "Available APKs:"
        find app/build/outputs -name "*.apk" -type f 2>/dev/null | head -10
        return 0
    fi

    echo "Starting Metro bundler in the background..."
    nohup npx react-native start --reset-cache > metro.log 2>&1 &
    echo "Waiting for Metro bundler to start..."
    until nc -z localhost 8081; do
        sleep 2
    done

    echo "Metro bundler is running on port 8081."
    
    adb install -r "$APK_PATH"
    echo "Jitsi Meet installed successfully."

    echo "Launching Jitsi Meet..."
    adb shell appops set org.jitsi.meet SYSTEM_ALERT_WINDOW allow #Ignore any popup windows asking for display over other apps
    adb shell am start -n org.jitsi.meet/.MainActivity
    echo "Jitsi Meet should now be running on your emulator."
}

install_jitsi
echo "Finished & Launched APK installation..."


#\\\CONFIGURING PROSODY CONTAINER SECTION///
echo "Looking for Prosody container..."
PROSODY_CONTAINER=$(docker ps --format '{{.Names}}' | grep prosody || true)
if [ -z "$PROSODY_CONTAINER" ]; then
    echo "[SKIP USER CREATION] Prosody container not found!"
    exit 0
fi
echo "Found Prosody container: $PROSODY_CONTAINER"

echo "Ensuring Prosody directories..."
docker exec --user root "$PROSODY_CONTAINER" mkdir -p /etc/prosody /etc/prosody/certs

echo "Writing minimal prosody.cfg.lua safely..."

docker exec -i --user root "$PROSODY_CONTAINER" tee /tmp/prosody.cfg.lua > /dev/null <<'EOF'
-- Minimal Prosody config for testing
admins = { }

modules_enabled = {
    "roster";
    "saslauth";
    "tls";
    "dialback";
    "admin_shell";
}

allow_registration = true

VirtualHost "shared_net"
    enabled = true
EOF

docker exec --user root "$PROSODY_CONTAINER" mv /tmp/prosody.cfg.lua /etc/prosody/prosody.cfg.lua

echo "[DEBUG] Contents of prosody.cfg.lua inside container:"
docker exec --user root "$PROSODY_CONTAINER" cat /etc/prosody/prosody.cfg.lua

echo "Creating test users..."
docker exec "$PROSODY_CONTAINER" prosodyctl register alice shared_net "twisted_fate$%^0192" || true
docker exec "$PROSODY_CONTAINER" prosodyctl register bob shared_net "fallen_skies_%92" || true
docker exec "$PROSODY_CONTAINER" prosodyctl register charlie shared_net "1ce_cr3am_sunda3$2" || true
docker exec "$PROSODY_CONTAINER" prosodyctl register usera shared_net "usera$+99pass43" || true

echo "Prosody setup complete."


