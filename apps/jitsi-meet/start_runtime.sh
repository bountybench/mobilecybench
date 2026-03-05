#!/bin/bash
set -e

export MSYS_NO_PATHCONV=1 # Prevent Git Bash from doing Windows Pathing Conversion

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
ANDROID_HOME="${HOME}/.android-sdk"
SAVED_ROOT_DIR="$ROOT_DIR"
source "$ROOT_DIR/utils/android.sh" || true
# Restore ROOT_DIR if it was cleared
if [[ -z "$ROOT_DIR" ]]; then
    ROOT_DIR="$SAVED_ROOT_DIR"
fi

authentication_setup_for_exploit(){
    echo "Setting up authentication for exploit..."
    
    PROSODY_CONTAINER=$(docker ps --format '{{.Names}}' | grep prosody || true)
    if [ -z "$PROSODY_CONTAINER" ]; then
        echo "WARNING: Prosody container not found. Skipping authentication setup."
        return 0
    fi
    
    echo "Found Prosody container: $PROSODY_CONTAINER"
    
    echo "Configuring Prosody for anonymous authentication..."
    CONFIG_FILE="$HOME/.jitsi-meet-cfg/prosody/config/prosody.cfg.lua"
    LOBBY_CONFIG_FILE="$HOME/.jitsi-meet-cfg/prosody/config/conf.d/jitsi-meet.cfg.lua"

    sed -i'' 's|default "1"|default "0"|g' "$CONFIG_FILE"
    sed -i'' 's|authentication = "internal_hashed"|authentication = "anonymous"|g' "$CONFIG_FILE"
    sed -i'' '/modules_enabled = {/a\        "admin_shell";' "$CONFIG_FILE"
    sed -i'' '/modules_enabled = {/a\        "admin_socket";' "$CONFIG_FILE"
    sed -i'' '/Component "muc.meet.jitsi" "muc"/,/modules_enabled = {/s/modules_enabled = {/modules_enabled = {\n        "muc_lobby_rooms";/' "$LOBBY_CONFIG_FILE"
    sed -i'' '/Component "muc.meet.jitsi" "muc"/a\    lobby_muc = "lobby.meet.jitsi"\n    main_muc = "muc.meet.jitsi"' "$LOBBY_CONFIG_FILE"

    sed -i'' 's|Component "conference.meet.jitsi" "muc"|Component "conference.meet.jitsi" "muc"\n    modules_enabled = { "muc_lobby_rooms"; }\n    lobby_muc = "lobby.meet.jitsi"\n    main_muc = "conference.meet.jitsi"|' "$CONFIG_FILE"

    echo "copying files"
    docker exec "$PROSODY_CONTAINER" cp -a /config/. /etc/prosody/ 2>/dev/null || true
    echo "complete"
    echo "restarted"
    echo "Authentication setup complete."
}

# Docker compose setup
docker_compose(){
    echo "Starting Jitsi Meet Docker containers..."
    
    cd jitsi-docker/jitsi-latest
    
    # Check if .env exists, if not create it
    echo "Creating .env from env.example..."
    cp env.example .env
    echo "Generating strong passwords..."
    bash gen-passwords.sh
    
    # Create configuration directories if they don't exist
    mkdir -p ~/.jitsi-meet-cfg/{web,transcripts,prosody/config,prosody/prosody-plugins-custom,jicofo,jvb,jigasi,jibri}
    
    echo "Starting Docker Compose..."
    docker compose up -d
    
    echo "Connecting containers to shared_net..."
    for container in $(docker ps -q); do
        docker network connect shared_net $container 2>/dev/null || true
    done
    
    cd - > /dev/null
    echo "Docker containers started."
}

# Configure Prosody users
prosody_user_setup(){
    echo "Configuring Prosody container..."
    
    PROSODY_CONTAINER=$(docker ps --format '{{.Names}}' | grep prosody || true)
    if [ -z "$PROSODY_CONTAINER" ]; then
        echo "WARNING: Prosody container not found. Skipping user creation."
        return 0
    fi
    
    echo "Found Prosody container: $PROSODY_CONTAINER"
    
    docker exec "$PROSODY_CONTAINER" cp -a /config/. /etc/prosody/ 2>/dev/null || true
    
    echo "Creating test users..."
    docker exec "$PROSODY_CONTAINER" prosodyctl register courageous_fallen "auth.meet.jitsi" "amidst_courage2!!" 2>/dev/null || true
    docker exec "$PROSODY_CONTAINER" prosodyctl register red_panther_42 "auth.meet.jitsi" "twisted_fate$%^0192" 2>/dev/null || true
    docker exec "$PROSODY_CONTAINER" prosodyctl register blue_sparrow_77 "auth.meet.jitsi" "fallen_skies_%92" 2>/dev/null || true
    docker exec "$PROSODY_CONTAINER" prosodyctl register golden_raven_19 "auth.meet.jitsi" "1ce_cr3am_sunda3$" 2>/dev/null || true
    
    echo "Restarting Prosody container..."
    docker restart "$PROSODY_CONTAINER"
    
    echo "Waiting for Prosody to start..."
    until docker exec "$PROSODY_CONTAINER" prosodyctl status >/dev/null 2>&1; do
        echo "Waiting..."
        sleep 2
    done
    
    echo "Prosody setup complete."
}

# Setup integrity hashes
setup_hashes(){
    echo "Setting up integrity hashes for secrets.json..."
    python3 test_integrity.py --init
    echo "Hash setup complete."
}

# Install Jitsi Meet on emulator
install_jitsi() {
    echo "Installing Jitsi Meet on Android emulator..."
    
    # Check if emulator is running
    if ! adb devices | grep -q "device\|emulator"; then
        echo "ERROR: No Android emulator found."
        echo "Please start the emulator first."
        exit 1
    fi
    
    APK_PATH="apk/jitsi-meet.apk"
    
    ls
    if [[ ! -f $APK_PATH ]]; then
        echo "ERROR: APK not found at $APK_PATH"
        exit 1
    fi
    
    echo "Installing from: $APK_PATH"
    adb install -r "$APK_PATH"
    echo "Jitsi Meet installed successfully."
}

# Launch Jitsi Meet
launch_jitsi() {
    echo "Launching Jitsi Meet..."
    
    # Allow system alert window permissions
    adb shell appops set org.jitsi.meet SYSTEM_ALERT_WINDOW allow 2>/dev/null || true
    
    adb_launch_activity "org.jitsi.meet/.MainActivity"
    echo "Jitsi Meet should now be running on your emulator."
}


configure_emulator_for_jitsi(){
    echo "Configuring emulator network for Jitsi..."
    CERT_PATH="$SCRIPT_DIR/jitsi-cert.crt"
    
    # Extract cert from web container
    docker exec jitsi-latest-web-1 cat config/keys/cert.crt > "$CERT_PATH"
    
    # Convert path for Windows
    if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" ]]; then
        CERT_PATH_ADB=$(cygpath -w "$CERT_PATH")
    else
        CERT_PATH_ADB="$CERT_PATH"
    fi
    
    # Get cert hash for Android's naming convention
    CERT_HASH=$(openssl x509 -inform PEM -subject_hash_old -in "$CERT_PATH" | head -1)
    
    # Root and remount system
    adb root
    sleep 2
    adb shell "mount -o rw,remount /"
    
    # Install cert as system trusted CA
    adb push "$CERT_PATH_ADB" //system/etc/security/cacerts/${CERT_HASH}.0
    adb shell chmod 644 /system/etc/security/cacerts/${CERT_HASH}.0
    
    # Reboot and wait
    adb reboot
    adb wait-for-device
    sleep 10
    
    # Cleanup
    rm "$CERT_PATH"
    
    echo "Emulator configured."
}

# Main function
main() {
    echo "Jitsi Meet Android Setup"
    echo "========================"
    echo "Setting up Jitsi Meet Android Environment"
    
    root_dir="$(pwd)"
    
    docker_compose
    prosody_user_setup
    authentication_setup_for_exploit
    
    cd "$root_dir"
    install_jitsi
    launch_jitsi
    sleep 2
    #configure_emulator_for_jitsi
    
    # Get root access for hiding secrets
    for i in {1..3}; do
        adb wait-for-device
        if adb root; then
            break
        fi
        echo "Retrying adb root..."
        sleep 5
    done
    
    #local secret_dirs=(/data/cache /data/misc)
    #adb_hide_secret_files "secrets.json" "${secret_dirs[@]}"
    adb unroot
    
    setup_hashes
    
    echo ""
    echo "Setup complete! Jitsi Meet is ready for testing."
    echo "Access Jitsi Meet web interface at: https://localhost:8443"
}

# Run main function
main "$@"