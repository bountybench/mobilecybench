#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "tindroid" "$@")
cd "$SCRIPT_DIR"

TARGET_PACKAGE="co.tinode.tindroidx"

setup_python_env() {
    log_info "Setting up Python virtual environment..."

    if [ ! -d "./venv" ]; then
        log_info "Creating virtual environment..."
        python3 -m venv ./venv
    fi

    source ./venv/bin/activate

    log_info "Installing Python packages from requirements.txt..."
    pip install -r requirements.txt

    log_info "Python environment setup complete!"
}

setup_env() {
    log_info "Setting up Tinode environment..."

    if [ ! -f .env ]; then
        log_info "Creating .env file with default values..."
        cat > .env <<EOF
# MySQL Configuration
MYSQL_ROOT_PASSWORD=root
MYSQL_USER=tinode
MYSQL_PASSWORD=tinode
MYSQL_DATABASE=tinode

# Tinode Server Configuration
TINODE_MYSQL_DSN="tinode:tinode@tcp(db)/tinode"
EOF
        log_info ".env file created with default values. You can modify it if needed, then re-run start_runtime.sh."
    fi

    source .env

    log_info "Generating init-db.sql with environment variables..."
    cat > init-db.sql <<EOF
DROP DATABASE IF EXISTS ${MYSQL_DATABASE};
DROP USER IF EXISTS '${MYSQL_USER}'@'%';
CREATE USER '${MYSQL_USER}'@'%' IDENTIFIED BY '${MYSQL_PASSWORD}';
GRANT ALL PRIVILEGES ON *.* TO '${MYSQL_USER}'@'%' WITH GRANT OPTION;
GRANT ALL PRIVILEGES ON ${MYSQL_DATABASE}.* TO '${MYSQL_USER}'@'%';
FLUSH PRIVILEGES;
EOF

    log_info "Running docker compose up to start the db and tinode-server containers..."
    docker compose -p tindroid up -d

    log_info "Waiting for the containers to be ready"

    while ! docker compose exec -T db mysqladmin ping -h localhost -u $MYSQL_USER -p$MYSQL_PASSWORD --silent 2>/dev/null; do
        log_info "Waiting for MySQL to be ready..."
        sleep 2
    done
    log_info "MySQL is ready!"

    while ! docker compose exec -T tinode-server nc -z localhost 6060 2>/dev/null; do
        log_info "Waiting for Tinode server to be ready..."
        sleep 2
    done
    log_info "Tinode server is ready!"

    log_info "Seeding database with seed_db.sql..."
    docker compose exec -T db mysql -u $MYSQL_USER -p$MYSQL_PASSWORD $MYSQL_DATABASE < seed_db.sql || fatal "Error seeding database!"

    log_info "Environment setup complete!"
}

install_app(){
  log_info "Installing Tindroid on Android device"
  adb_install_apk "$APK_PATH"

  log_info "Launching Tindroid..."
  adb shell am start -n co.tinode.tindroidx/co.tinode.tindroid.InitRouterActivity
  sleep 2
}

main(){
  log_info "Setting up Python environment"
  setup_python_env

  log_info "Generating secrets"
  python3 seed_secrets_and_db.py || fatal "Secrets generation failed"

  log_info "Setting up docker containers"
  setup_env || fatal "Docker containers setup failed"

  log_info "Setting up app"
  install_app

  log_info "Logging in to the Tindroid app"
  if python3 -c "from tindroid_login import test_tinode_login; success, msg = test_tinode_login('user_a', 'user_a123'); exit(0 if success else 1)"; then
      log_info "Login test successful"
  else
      log_warn "Login test failed"
  fi
}

main "$@"
