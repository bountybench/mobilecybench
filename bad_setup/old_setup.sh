#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
ANDROID_HOME="${HOME}/.android-sdk"
source "$ROOT_DIR/utils/android.sh"
command_exists(){ command -v "$1" >/dev/null 2>&1; }
DOMAIN="localhost"
ENV_FILE="./flexiapi/flexiapi/.env"
ADMIN_USER="admin"
ADMIN_PASS="adminpass"

pip install uiautomator2
pip install psycopg2-binary
pip install bcrypt

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
    APK_PATH="app/build/outputs/apk/release/linphone-android-release-6.0.18.apk"
   
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
  cp ./.env ./flexiapi/flexiapi
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

  echo "Waiting for Flexiapi container health check..."
  for i in {1..30}; do
    health_status=$(docker inspect --format='{{.State.Health.Status}}' account_manager 2>/dev/null || echo "no-health")
    if [ "$health_status" = "healthy" ]; then
      echo "Flexiapi container is healthy"
      break
    fi
    if [ $i -eq 30 ]; then
      echo "Flexiapi health check still not healthy, proceeding anyway..."
    fi
    sleep 15
  done

  # Adjust this depending on your network and ports in docker-compose.yml
  echo "Flexisip server ready at sip:10.0.2.2:5060 (UDP/TCP) and sip:10.0.2.2:5061 (TLS)"

  ## Configuring the account_manager/flexiapi
  if [ ! -f "$ENV_FILE" ]; then
    echo "Creating new .env file for FlexiAPI..."
    cat > "$ENV_FILE" <<EOF
APP_ENV=production
APP_KEY=
APP_URL=http://localhost:8080
APP_ROOT_HOST=$DOMAIN

DB_CONNECTION=pgsql
DB_HOST=account_db
DB_PORT=5432
DB_DATABASE=flexisip_accounts
DB_USERNAME=flexisip
DB_PASSWORD=flexipass
EOF
fi

  # Generate APP_KEY
  if ! grep -q "APP_KEY=base64" "$ENV_FILE"; then
      echo "Generating Laravel APP_KEY..."
      APP_KEY=$(docker exec account_manager php artisan key:generate --show)
      sed -i "s|APP_KEY=.*|APP_KEY=$APP_KEY|" "$ENV_FILE"
      echo "App key set in $ENV_FILE"
  fi
  
  # Create a space
  DOMAIN="10.0.2.2"
  echo "Creating first Space for domain '$DOMAIN'..."
  docker exec account_manager php artisan spaces:create-update "$DOMAIN" "$DOMAIN" "Super Space" --super || true

  # Create admin
  echo "Creating admin user ($ADMIN_USER)..."
  docker exec account_manager php artisan accounts:create-admin-account -u "$ADMIN_USER" -p "$ADMIN_PASS" -d "$DOMAIN" || true

  # Seed Users
  echo "Creating test users..."
  docker exec account_manager php artisan accounts:create-admin-account -u usera -p userAPW123 -d "$DOMAIN" || true
  docker exec account_manager php artisan accounts:create-admin-account -u user1 -p userAPW123 -d "$DOMAIN" || true
  docker exec account_manager php artisan accounts:create-admin-account -u user2 -p userAPW123 -d "$DOMAIN" || true
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
    
    echo "grabbing account_manager repo: release/2.0"
    cd flexiapi
    git checkout release/2.0
    cd ..

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