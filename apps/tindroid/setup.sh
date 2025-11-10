#!/usr/bin/env bash
# Environment + baseline setup script for Tindroid CIAA tests.
# Steps:
#   1. Verify prerequisites (docker, python3, adb)
#   2. Launch docker-compose stack (Tinode + DB)
#   3. Wait for container health
#   4. Install required Python packages
#   5. Generate secrets and seed database
#   6. Install Android app (expects APK at apps/tindroid/apk/tindroid.apk)
#   7. Run login test
# Usage:
#   ./setup.sh
# Note: APK should be built/downloaded before running this script:
#   - Build from source: ./setup_app_source.sh
#   - Download from link: python ../../setup_app_apklink.py tindroid
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}" )" && pwd)"
CODEBASE_DIR="${SCRIPT_DIR}/codebase"
LOG_PREFIX="[setup]"

TARGET_PACKAGE="co.tinode.tindroidx"

# Logging functions
info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*"; }
fail(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*" >&2; exit 1; }

# Function to run commands with timeout
run_with_timeout() {
    local timeout_seconds=300  # 5 minutes
    local cmd="$1"
    
    echo "Running command with timeout (${timeout_seconds}s): $cmd"
    
    if timeout "$timeout_seconds" bash -c "$cmd"; then
        echo "Command completed successfully"
        return 0
    else
        local exit_code=$?
        if [ $exit_code -eq 124 ]; then
            echo "ERROR: Command timed out after ${timeout_seconds} seconds"
        else
            echo "ERROR: Command failed with exit code $exit_code"
        fi
        return $exit_code
    fi
}

log_info() {
    info "$1"
}

log_success() {
    echo -e "✅ $1\n"
}

log_error() {
    fail "$1"
}

# Setup Python virtual environment
setup_python_env() {
    echo "Setting up Python virtual environment..."
    
    # Create virtual environment if it doesn't exist
    if [ ! -d "./venv" ]; then
        echo "Creating virtual environment..."
        python3 -m venv ./venv
    fi
    
    # Activate virtual environment
    source ./venv/bin/activate
    
    # Install requirements
    echo "Installing Python packages from requirements.txt..."
    pip install -r requirements.txt
    
    echo "Python environment setup complete!"
}

setup_env() {
    echo "Setting up Tinode environment..."
    echo "==================="

    # Check if .env file exists
    if [ ! -f .env ]; then
        echo "Creating .env file with default values..."
        cat > .env <<EOF
# MySQL Configuration
MYSQL_ROOT_PASSWORD=root
MYSQL_USER=tinode
MYSQL_PASSWORD=tinode
MYSQL_DATABASE=tinode

# Tinode Server Configuration
TINODE_MYSQL_DSN="tinode:tinode@tcp(db)/tinode"
EOF
        echo ".env file created with default values. You can modify it if needed, then re-run setup.sh."
    fi

    # Load environment variables
    source .env

    # Generate init-db.sql with environment variables
    echo "Generating init-db.sql with environment variables..."
    cat > init-db.sql <<EOF
DROP DATABASE IF EXISTS ${MYSQL_DATABASE};
DROP USER IF EXISTS '${MYSQL_USER}'@'%';
CREATE USER '${MYSQL_USER}'@'%' IDENTIFIED BY '${MYSQL_PASSWORD}';
GRANT ALL PRIVILEGES ON *.* TO '${MYSQL_USER}'@'%' WITH GRANT OPTION;
GRANT ALL PRIVILEGES ON ${MYSQL_DATABASE}.* TO '${MYSQL_USER}'@'%';
FLUSH PRIVILEGES;
EOF

    echo "Running docker compose up to start the db and tinode-server containers..."
    docker compose -p tindroid up -d # Use tindroid as the project name

    echo "Waiting for the containers to be ready"
    echo "==================="

    while ! docker compose exec -T db mysqladmin ping -h localhost -u $MYSQL_USER -p$MYSQL_PASSWORD --silent; do
        echo "Waiting for MySQL to be ready..."
        docker compose logs db
        echo "==================="
        docker compose logs tinode-server
        echo "==================="

        sleep 2
    done
            echo "MySQL is ready!"

    while ! docker compose exec -T tinode-server nc -z localhost 6060; do
        echo "Waiting for Tinode server to be ready..."
        docker compose logs db
        echo "==================="
        docker compose logs tinode-server
        echo "==================="
        sleep 2
    done
            echo "Tinode server is ready!"

    echo "Seeding database with seed_secrets.sql..."
    docker compose exec -T db mysql -u $MYSQL_USER -p$MYSQL_PASSWORD $MYSQL_DATABASE < seed_secrets.sql

    if [ $? -eq 0 ]; then
                echo "Database seeded successfully!"
                else
        echo "Error seeding database!"
                    exit 1
    fi

    echo "Environment setup complete! Tinode server should be running on port 6060"
    echo "You can check the logs with: docker compose logs -f tinode-server"
}

pkg_name="co.tinode.tindroidx"

install_tindroid(){
  info "Installing Tindroid on Android device"
  adb wait-for-device
  if ! adb get-state >/dev/null 2>&1; then
    fail "No adb device detected; ensure emulator is running"
  fi


  # Look for APK in the tindroid/apk directory
  local apk="${SCRIPT_DIR}/apk/tindroid.apk"

  if [[ ! -f "$apk" ]]; then
    fail "Could not find APK at $apk. IMPORTANT: Build or download APK first:" \
         "  - Build from source: ./setup_app_source.sh" \
         "  - Download from link: python ../../setup_app_apklink.py tindroid"
  fi

  info "Installing APK: $apk"
  adb install -r "$apk"
  
  info "Tindroid installed successfully."
}

launch_tindroid(){
  info "Launching Tindroid..."
  adb shell am start -n co.tinode.tindroidx/co.tinode.tindroid.InitRouterActivity
  
  # Check if the app process is running
  sleep 2
  if adb shell pgrep -f "$TARGET_PACKAGE" >/dev/null 2>&1; then
    info "Tindroid launched successfully."
  else
    warn "Tindroid may not have launched properly (process not found)."
  fi
}

install_app(){
  if ! command -v adb >/dev/null 2>&1; then
    fail "adb not found; cannot install Android app"
  fi
  install_tindroid
  launch_tindroid
}

main(){
  echo === RUNNING setup.sh ===

  # Setup Python virtual environment and install packages
  log_info "=== Setting up Python environment ==="
  setup_python_env

  log_info "=== Generating secrets ==="
  if python3 generate_secrets.py; then
      log_success "Secrets generated successfully"
  else
      log_error "Secrets generation failed"
  fi

  log_info "=== Setting up docker containers ==="
  if setup_env; then
      log_success "Docker containers setup successfully"
  else
      log_error "Docker containers setup failed"
  fi

  log_info "=== Setting up app ==="
  install_app

  log_info "=== Logging in to the Tindroid app ==="

  # Verify app setup by testing WebSocket login using user_a's credentials
  if python3 -c "from tindroid_login import test_tinode_login; success, msg = test_tinode_login('user_a', 'user_a123'); exit(0 if success else 1)"; then
      log_success "Login test successful"
  else
      log_info "Warning: Login test failed"
  fi

  echo === FINISHED setup.sh ===
}

main "$@"