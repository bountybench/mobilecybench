#!/bin/bash
set -e

# Make sure the emulator has already started running, if running this script locally.
if [[ -z "${CI:-}" && -z "${GITHUB_ACTIONS:-}" ]]; then
    ../../stop_emulator.sh
    ../../start_emulator.sh
    adb wait-for-device
    while [ "`adb shell getprop sys.boot_completed | tr -d '\r' `" != "1" ] ; do sleep 1; done
fi

# Adapted from Tindroid setup
install_python_package() {
    local package_name="$1"
    local import_name="${2:-$1}"
    
    echo "Checking if $package_name is available..."
    
    # Check if we're in a CI environment (GitHub Actions, etc.)
    if [[ -n "${CI:-}" || -n "${GITHUB_ACTIONS:-}" ]]; then
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

install_python_package "uiautomator2"

docker compose up --build -d

./setup_app_apklink.sh

sleep 2
docker exec -it home-assistant-server \
  curl -i -X POST "http://home-assistant-server:8123/api/onboarding/users" \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "http://home-assistant-server:8123/",
    "name": "testuser",
    "username": "testuser",
    "password": "testuser123",
    "language": "en"
  }'

if [[ -n "${CI:-}" || -n "${GITHUB_ACTIONS:-}" ]]; then
    if python3 setup_home_assistant.py --username testuser --hostname home-assistant-server; then
        echo "Login test successful"
    else
        echo "Warning: Login test failed"
    fi
else
    if python3 setup_home_assistant.py --username testuser --hostname 10.0.2.2; then
        echo "Login test successful"
    else
        echo "Warning: Login test failed"
    fi
fi