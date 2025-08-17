#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
set -e

log_info() {
    echo -e "[INFO] $1\n"
}

log_success() {
    echo -e "✅ $1\n"
}

log_error() {
    echo -e "❌ [ERROR] $1\n" >&2
    exit 1
}

generate_secrets() {
    echo "Generating secrets..."
    echo "==================="
    if [[ "$(which pip)" == *".venv"* ]]; then
        echo "Using .venv's pip"
        pip install bcrypt
        python3 generate_secrets.py
    else
        echo "This script needs to install bcrypt to generate secrets."
        read -p "You're not using a virtual environment. Proceed with installing bcrypt using the current pip located at $(which pip)? (y/n): " choice
        if [[ "$choice" == "y" || "$choice" == "Y" ]]; then
            pip install bcrypt
            python3 generate_secrets.py
        else
            echo "Aborting. Please set up your .venv and rerun this script."
            exit 1
        fi
    fi
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

    echo "Running docker compose up to start the db and tinode-server containers..."
    docker-compose up -d

    echo "Waiting for the containers to be ready"
    echo "==================="

    while ! docker-compose exec -T db mysqladmin ping -h localhost -u $MYSQL_USER -p$MYSQL_PASSWORD --silent; do
        echo "Waiting for MySQL to be ready..."
        sleep 2
    done
    echo "MySQL is ready!"

    while ! curl -s http://localhost:6060/v0/ > /dev/null 2>&1; do
        echo "Waiting for Tinode server to be ready..."
        sleep 2
    done
    echo "Tinode server is ready!"

    echo "Seeding database with seed_secrets.sql..."
    docker-compose exec -T db mysql -u $MYSQL_USER -p$MYSQL_PASSWORD $MYSQL_DATABASE < seed_secrets.sql

    if [ $? -eq 0 ]; then
        echo "Database seeded successfully!"
    else
        echo "Error seeding database!"
        exit 1
    fi

    echo "Environment setup complete! Tinode server should be running on port 6060"
    echo "You can check the logs with: docker-compose logs -f tinode-server"
}

pkg_name="co.tinode.tindroidx"

echo === RUNNING setup.sh ===

log_info "=== Generating secrets ==="
if generate_secrets; then
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
echo "Attempting to install Tindroid using pre-built APK..."
chmod u+x setup_app_apklink.sh
if ./setup_app_apklink.sh; then
    log_success "Tindroid installed successfully using pre-built APK"
else
    log_info "Pre-built APK installation failed, falling back to source build..."
    chmod u+x setup_app_source.sh
    if ./setup_app_source.sh; then
        log_success "Tindroid installed successfully using source build"
    else
        log_error "Both APK link and source build failed."
    fi
fi

echo === FINISHED setup.sh ===