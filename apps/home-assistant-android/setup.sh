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

# Launch Home Assistant
launch_home_assistant() {
    echo "Launching Home Assistant (from source)..."
    adb shell pm list packages | grep -q "io.homeassistant.companion.android.minimal$" || {
        echo "ERROR: Home Assistant package not found on device/emulator."
        echo "Please ensure the app is installed correctly."
        exit 1
    }
    adb shell pm grant io.homeassistant.companion.android.minimal android.permission.POST_NOTIFICATIONS
    adb shell monkey -p io.homeassistant.companion.android.minimal -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
    echo "Home Assistant should now be running on your emulator."
}

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

main() {
    install_python_package "uiautomator2"

    docker compose up --build -d

    # Don't favor APK-link installation. In the future, we can add this as a flag for this file.
    # ./setup_app_apklink.sh

    install_home_assistant
    launch_home_assistant

        sleep 2
        if [ -t 1 ]; then
                DOCKER_TTY_FLAGS="-it"
        else
                DOCKER_TTY_FLAGS=""
        fi

        echo "Submitting onboarding user via Home Assistant API (CI friendly)..."
        docker exec $DOCKER_TTY_FLAGS home-assistant-server \
            curl -s -o /tmp/onboard_resp.txt -w "%{http_code}\n" -X POST "http://home-assistant-server:8123/api/onboarding/users" \
            -H "Content-Type: application/json" \
            -d '{
                "client_id": "http://home-assistant-server:8123/",
                "name": "testuser",
                "username": "testuser",
                "password": "testuser123",
                "language": "en"
            }' | {
                read code; \
                echo "Onboarding API HTTP status: $code"; \
                if [ "$code" != "200" ] && [ "$code" != "201" ]; then
                        echo "Onboarding request failed (status $code)" >&2
                        echo "Response body:" >&2
                        docker exec $DOCKER_TTY_FLAGS home-assistant-server cat /tmp/onboard_resp.txt || true
                fi
            }

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