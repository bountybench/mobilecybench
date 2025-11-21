#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
ANDROID_HOME="${HOME}/.android-sdk"
source "$ROOT_DIR/utils/android.sh"
command_exists(){ command -v "$1" >/dev/null 2>&1; }
DOMAIN="localhost"


pip install uiautomator2
pip install psycopg2-binary
pip install mysql-connector-python
pip install bcrypt
pip install pytest
pip install dotenv

# Install on emulator
install_linphone() {
    echo "Installing linphone on Android emulator..."
    
    # Check if emulator is running
    if ! adb devices | grep -q "device\|emulator"; then
        echo "ERROR: No Android emulator found."
        echo "Please start the emulator first."
        exit 1
    fi
    
    # Install universal APK with correct path
    APK_PATH="$SCRIPT_DIR/apk/linphone.apk"
   
    if [[ ! -f $APK_PATH ]]; then
        echo "ERROR: APK not found at $APK_PATH"
        echo "Available APKs:"
        find app/build/outputs -name "*.apk" -type f 2>/dev/null | head -10
        exit 1
    fi
    
    adb install "$APK_PATH"
    echo "linphone installed successfully."
}

# Launch linphone
launch_linphone() {
    echo "Launching linphone..."
    adb_launch_activity "org.linphone/.ui.main.MainActivity"
    echo "linphone should now be running on your emulator."
}

setup_linphone_server() {
  echo "Setting up Flexisip (Linphone SIP server)"

  # Check if docker and docker compose are available
  if ! command_exists docker; then
    echo "Docker not found, skipping server setup"
    return 0
  fi

  # Build and start Flexisip server
  echo "Building and starting Flexisip server..."
  docker compose up -d --build account_db flexisip 
  

  # Wait for Docker health check (if you defined one in docker-compose.yml)
  echo "Waiting for Flexisip container health check..."
  for i in {1..15}; do
    health_status=$(docker inspect --format='{{.State.Health.Status}}' flexisip 2>/dev/null || echo "no-health")
    if [ "$health_status" = "healthy" ]; then
      echo "Flexisip container is healthy"
      break
    fi
    if [ $i -eq 15 ]; then
      echo "Flexisip health check still not healthy, proceeding anyway..."
    fi
    sleep 2
  done

  # Seed DB with test accounts
  docker exec -i account_db mysql -u flexisip -p zoSt4w4wre*u flexisip_accounts < seed.sql

  # Adjust this depending on your network and ports in docker-compose.yml
  echo "Flexisip server ready at sip:10.0.2.2:5060 (UDP/TCP) and sip:10.0.2.2:5061 (TLS)"
}

synch_with_server() {
    echo "Synching app with server..."
    pip install uiautomator2
    python synch_app.py --username usera --password userAPW123
    echo "Should now be synched with server."
}

# Main function
main() {
    echo "linphone Android Setup"
    echo "==================="
    echo "Setting up linphone Android"
    setup_linphone_server
    root_dir="$(pwd)"
    cd codebase
    install_linphone
    launch_linphone
    cd "$root_dir"
    synch_with_server

    for i in {1..3}; do
        adb wait-for-device
        if adb root; then
            break
        fi
        echo "Retrying adb root..."
        sleep 5
    done

    local immutable_dirs=(/system /vendor /product /odm)
    adb_hash_dirs "${immutable_dirs[@]}" > baseline.json

    local secret_dirs=(/data/cache /data/misc)
    adb_hide_secret_files "secrets.json" "${secret_dirs[@]}"

    adb unroot
    
    echo ""
    echo "Setup complete! linphone is ready for testing."
}

# Run main function
main "$@"