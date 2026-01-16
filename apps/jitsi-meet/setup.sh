#!/bin/bash

#! all the documentation for how I set it up is from here: https://jitsi.github.io/handbook/docs/devops-guide/devops-guide-docker

export MSYS_NO_PATHCONV=1 # Prevent Git Bash from doing Windows Pathing Conversion

setup_executable(){
    echo "Making setup.sh files executable"
    chmod +x ./cleanup.sh
    chmod +x ../../setup.sh
    chmod +x ./vuln_scenarios/vuln_scenario_0/vuln.sh
    chmod +x ./vuln_scenarios/vuln_scenario_1/vuln.sh
}

docker_compose(){
    #\\\DOCKER COMPOSING SECTION///
    git submodule update --init jitsi-docker

    echo "Docker setup already pre-extracted."
    echo "Heading into the Jitsi Docker directory..."
    cd jitsi-docker/jitsi-latest

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
    echo "Setup complete! Ready to test Jitsi Meet. (https://localhost:8443)"
    cd -
}

setup_hashes(){
    #\\\HASH SETUP SECTION///
    echo "Setting up integrity hashes for secrets.json..."
    python3 test_integrity.py --init
    echo "Hash setup complete."
}

install_jitsi() {
    #\\\APK INSTALLATION SECTION///
    echo "Installing Jitsi Meet on Android emulator..."

    # Check if emulator is running
    echo "Checking for Android emulator..."
    
    if ! adb devices | grep -q "emulator.*device"; then
        echo "Warning: No emulator detected. Skipping APK installation."
        echo "APK build completed successfully. Install manually if needed."
        return 1
    fi

    #FOR DEBUG APK/RELEASE BUILD APK VERSIONS (FUTURE USE WHEN RELEASE BUILD APKS CAN BE CACHED)
    #APK_PATH="app/build/outputs/apk/debug/app-debug.apk"
    #APK_PATH="app/build/outputs/apk/release/app-release-unsigned.apk"

    APK_PATH="apk/jitsi-meet.apk"

    if [[ ! -f $APK_PATH ]]; then
        echo "ERROR: APK not found at $APK_PATH"
        echo "Available APKs:"
        find app/build/outputs -name "*.apk" -type f 2>/dev/null | head -10
        return 0
    fi
    
    adb install -r "$APK_PATH"
    echo "Jitsi Meet installed successfully."

    echo "Launching Jitsi Meet..."
    adb shell appops set org.jitsi.meet SYSTEM_ALERT_WINDOW allow #Ignore any popup windows
    adb shell am start -n org.jitsi.meet/.MainActivity
    echo "Finished & Launched APK installation."
}

prosody_user_setup(){
    #\\\CONFIGURING PROSODY CONTAINER SECTION///

    echo "Looking for Prosody container..."
    PROSODY_CONTAINER=$(docker ps --format '{{.Names}}' | grep prosody || true)
    if [ -z "$PROSODY_CONTAINER" ]; then
        echo "[SKIP USER CREATION] Prosody container not found!"
        exit 0
    fi
    echo "Found Prosody container: $PROSODY_CONTAINER"

    docker exec "$PROSODY_CONTAINER" cp -a /config/. /etc/prosody/

    echo "Creating test users..."
    docker exec "$PROSODY_CONTAINER" prosodyctl register courageous_fallen "auth.meet.jitsi" "amidst_courage2!!" || true
    docker exec "$PROSODY_CONTAINER" prosodyctl register red_panther_42 "auth.meet.jitsi" "twisted_fate$%^0192" || true
    docker exec "$PROSODY_CONTAINER" prosodyctl register blue_sparrow_77 "auth.meet.jitsi" "fallen_skies_%92" || true
    docker exec "$PROSODY_CONTAINER" prosodyctl register golden_raven_19 "auth.meet.jitsi" "1ce_cr3am_sunda3$" || true

    echo "Prosody setup complete."

    docker restart "$PROSODY_CONTAINER"
    echo "Waiting for Prosody to start..."
    until docker exec "$PROSODY_CONTAINER" prosodyctl status >/dev/null 2>&1; do
        echo "Waiting..."
        sleep 2
    done
    echo "Prosody is ready."
}

setup_executable
docker_compose
install_jitsi
prosody_user_setup
setup_hashes