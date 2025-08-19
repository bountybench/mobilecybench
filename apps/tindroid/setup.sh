#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
set -e

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
    echo -e "[INFO] $1\n"
}

log_success() {
    echo -e "✅ $1\n"
}

log_error() {
    echo -e "❌ [ERROR] $1\n" >&2
    exit 1
}

# Helper function to install Python packages with proper environment detection
install_python_package() {
    local package_name="$1"
    local import_name="${2:-$1}"
    
    echo "Checking if $package_name is available..."
    
    # Check if we're in a CI environment (GitHub Actions, etc.)
    if [[ -n "$CI" || -n "$GITHUB_ACTIONS" ]]; then
        echo "Detected CI environment, using system Python and pip"
        # In CI, packages should already be installed from requirements.txt
        if python3 -c "import $import_name" 2>/dev/null; then
            echo "$package_name is already available"
            return 0
        else
            echo "Installing $package_name for CI environment..."
            run_with_timeout "pip install $package_name"
            return $?
        fi
    else
        # Not in CI - check for virtual environment or proceed with system pip
        if [[ "$(which pip)" == *".venv"* ]]; then
            echo "Using .venv's pip"
            pip install "$package_name"
            return $?
        else
            echo "This script needs to install $package_name."
            echo "You're not using a virtual environment."
            read -p "Proceed with installing $package_name using the current pip located at $(which pip)? (y/n): " choice
            if [[ "$choice" == "y" || "$choice" == "Y" ]]; then
                echo "Proceeding with installation..."
                pip install "$package_name"
                return $?
            else
                echo "Aborting. Please set up your .venv and rerun this script."
                return 1
            fi
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
    docker compose up -d

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

echo === RUNNING setup.sh ===

# Install required Python packages at the start
log_info "=== Installing required Python packages ==="
if install_python_package "bcrypt"; then
    log_success "bcrypt package is available"
else
    log_error "Failed to install bcrypt"
fi

if install_python_package "uiautomator2"; then
    log_success "uiautomator2 package is available"
else
    log_error "Failed to install uiautomator2"
fi

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
        exit 1
    fi
fi

log_info "=== Logging in to the Tindroid app ==="

# Test the app setup by running a quick tindroid login test
if python3 tindroid_login.py --username user_a --password user_a123 --logout-after; then
    log_success "Login test successful"
else
    log_info "Warning: Login test failed"
fi

echo === FINISHED setup.sh ===