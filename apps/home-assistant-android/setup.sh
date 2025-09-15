#!/bin/bash
set -e

# Initialize installation of Home Assistant
install_home_assistant() {
    echo "Installing Home Assistant APK on connected device/emulator..."

    # Check if emulator is running
    if ! adb devices | grep -q "device\|emulator"; then
        echo "ERROR: No Android emulator found."
        echo "Please start the emulator first."
        exit 1
    fi

    APK_PATH="codebase/app/build/outputs/apk/minimal/debug/app-minimal-debug.apk"

    if [[ ! -f $APK_PATH ]]; then
        echo "ERROR: APK not found at $APK_PATH"
        echo "Available APKs:"
        find codebase/app/build/outputs -name "*.apk" -type f 2>/dev/null | head -10
        exit 1
    fi

    # Install new APK (expected applicationId: io.homeassistant.companion.android.minimal)
    adb install -r "$APK_PATH"
    echo "Installed Home Assistant successfully."
}

# Some functions below are adapted from Tindroid setup

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

# Launch Home Assistant
launch_home_assistant() {
    echo "Launching Home Assistant..."
    adb shell pm list packages | grep -q "io.homeassistant.companion.android.minimal$" || {
        echo "ERROR: Home Assistant package not found on device/emulator."
        echo "Please ensure the app is installed correctly."
        exit 1
    }
    adb shell pm grant io.homeassistant.companion.android.minimal android.permission.POST_NOTIFICATIONS
    adb shell monkey -p io.homeassistant.companion.android.minimal -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
    echo "Home Assistant should now be running on your emulator."
}

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

seed_home_assistant_config() {
    echo "Seeding Home Assistant config (if needed)..."
    mkdir -p ./config/.storage

    # Seed configuration.yaml if missing or empty
    if [ ! -s ./config/configuration.yaml ]; then
        cp ./seeded-files/demo-configuration.yaml ./config/configuration.yaml
        echo "Seeded configuration.yaml from seeded-files/demo-configuration.yaml"
    else
        echo "configuration.yaml already exists and is non-empty; skipping seed"
    fi

    # Create empty included files if they don't exist
    # These are referenced by configuration.yaml with !include directives
    for file in automations.yaml scripts.yaml scenes.yaml; do
        if [ ! -f "./config/$file" ]; then
            echo "[]" > "./config/$file"
            echo "Created empty $file"
        fi
    done

    # Auth files (only if absent)
    if [ ! -f ./config/.storage/auth ]; then
        cp ./seeded-files/demo-auth ./config/.storage/auth
        chmod 644 ./config/.storage/auth
        echo "Seeded auth file"
    fi
    if [ ! -f ./config/.storage/auth_provider.homeassistant ]; then
        cp ./seeded-files/demo-auth_provider.homeassistant ./config/.storage/auth_provider.homeassistant
        chmod 644 ./config/.storage/auth_provider.homeassistant
        echo "Seeded auth_provider.homeassistant file"
    fi
    
    # Ensure auth files have proper permissions for CI environments
    if [ -f ./config/.storage/auth ]; then
        chmod 644 ./config/.storage/auth
    fi
    if [ -f ./config/.storage/auth_provider.homeassistant ]; then
        chmod 644 ./config/.storage/auth_provider.homeassistant
    fi

    # Onboarding file (if provided and not present)
    if [ -f ./seeded-files/seeded-onboarding-file ] && [ ! -f ./config/.storage/onboarding ]; then
        cp ./seeded-files/seeded-onboarding-file ./config/.storage/onboarding
        echo "Seeded onboarding file"
    fi
}

main() {
    install_python_package "uiautomator2"
    install_python_package "websocket-client"
    install_python_package "playwright"
    
    # Install Playwright browsers after installing the package
    echo "Installing Playwright browsers..."
    run_with_timeout "playwright install chromium"

    # Setup user accounts and generate secrets
    echo "Setting up user accounts and credentials..."
    python3 setup_accounts.py
    python3 generate_secrets.py

    # Seed files BEFORE starting container so directory mount contains them
    seed_home_assistant_config

    docker compose up --build -d

    # Don't favor APK-link installation. In the future, we can add this as a flag for this file.
    # ./setup_app_apklink.sh

    # Comment out if uncommenting APK-link installation.
    ./setup_app_source.sh
    install_home_assistant

    launch_home_assistant
    if [[ -n "${CI:-}" || -n "${GITHUB_ACTIONS:-}" ]]; then
        if python3 setup_home_assistant.py --username testuser --hostname home-assistant-server; then
            echo "Setting-up test successful"
        else
            echo "Warning: Setting-up test failed"
        fi
    else
        if python3 setup_home_assistant.py --username testuser --hostname 10.0.2.2; then
            echo "Setting-up test successful"
        else
            echo "Warning: Setting-up test failed"
        fi
    fi
}

main "$@"