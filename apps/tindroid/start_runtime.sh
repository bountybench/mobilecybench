#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}" )" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "tindroid" "$@")
LOG_PREFIX="[setup]"

TARGET_PACKAGE="co.tinode.tindroidx"

info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*"; }
fail(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*" >&2; exit 1; }

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
        echo ".env file created with default values. You can modify it if needed, then re-run start_runtime.sh."
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

    while ! docker compose exec -T db mysqladmin ping -h localhost -u $MYSQL_USER -p$MYSQL_PASSWORD --silent 2>/dev/null; do
        echo "Waiting for MySQL to be ready..."
        sleep 2
    done
    echo "MySQL is ready!"

    while ! docker compose exec -T tinode-server nc -z localhost 6060 2>/dev/null; do
        echo "Waiting for Tinode server to be ready..."
        sleep 2
    done
    echo "Tinode server is ready!"

    echo "Seeding database with seed_db.sql..."
    docker compose exec -T db mysql -u $MYSQL_USER -p$MYSQL_PASSWORD $MYSQL_DATABASE < seed_db.sql || { echo "Error seeding database!"; exit 1; }

    echo "Environment setup complete!"
}

install_app(){
  info "Installing Tindroid on Android device"
  adb_install_apk "$APK_PATH"

  info "Launching Tindroid..."
  adb shell am start -n co.tinode.tindroidx/co.tinode.tindroid.InitRouterActivity
  sleep 2
}

main(){
  info "=== Setting up Python environment ==="
  setup_python_env

  info "=== Generating secrets ==="
  python3 seed_secrets_and_db.py || fail "Secrets generation failed"

  info "=== Setting up docker containers ==="
  setup_env || fail "Docker containers setup failed"

  info "=== Setting up app ==="
  install_app

  info "=== Logging in to the Tindroid app ==="
  if python3 -c "from tindroid_login import test_tinode_login; success, msg = test_tinode_login('user_a', 'user_a123'); exit(0 if success else 1)"; then
      info "Login test successful"
  else
      warn "Login test failed"
  fi
}

main "$@"