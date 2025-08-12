#!/usr/bin/env bash
set -e  # Stop script on error

# General variables
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="codebase"

# Android SDK variables
ANDROID_HOME="${HOME}/.android-sdk"
AVD_NAME="Pixel_2_API_28"   

# Set APK path dynamically
APK_REL="seafile_3.0.16_patch3.apk"  # Set to debug by default
APK_PATH="./${APK_REL}"

# Seafile variables
SEAFILE_SITE_URL="10.0.2.2:8000"
SEAFILE_USER="anarchist@example.com"   # Logging in as normal user
SEAFILE_PASS="zU72wO7eX4UZ"
SEADROID_PACKAGE="com.seafile.seadroid2"


# Ensures a dependency is installed, prompting the user to install it if missing.
# Arguments:
#   $1: Dependency name for display (e.g., "Java 17").
#   $2: Command to check if the dependency is installed (e.g., "command -v git").
#   $3: Package name for Homebrew.
#   $4: Package name for apt-get.
ensure_dependency() {
    local name="$1"
    local check_command="$2"
    local brew_package="$3"
    local apt_package="$4"

    # Use eval to handle complex check commands with pipes and quotes.
    if ! eval "$check_command" >/dev/null 2>&1; then
        echo "⚠️ WARNING: ${name} is not installed."
        read -p "Would you like to attempt to install ${name}? (y/N) " -n 1 -r REPLY
        echo

        if [[ "$REPLY" =~ ^[Yy]$ ]]; then
            echo "Attempting to install ${name}..."
            if command -v brew >/dev/null 2>&1; then
                brew install "$brew_package"
            elif command -v apt-get >/dev/null 2>&1; then
                sudo apt-get update && sudo apt-get install -y "$apt_package"
            else
                echo "❌ ERROR: Could not determine package manager. Please install ${name} manually."
                exit 1
            fi
            # Verify after attempting installation.
            if ! eval "$check_command" >/dev/null 2>&1; then
                 echo "❌ ERROR: ${name} installation failed. Please install it manually."
                 exit 1
            fi
            echo "✅ ${name} installed successfully."
        else
            echo "❌ ERROR: ${name} is a required dependency. Exiting."
            exit 1
        fi
    else
        echo "✅ ${name} is installed."
    fi
}


# Checks to make sure Java, Android SDK, and Git are installed
check_prerequisites() {
    ensure_dependency "Java 17" "java -version 2>&1 | grep 'openjdk version \"17'" "openjdk@17" "openjdk-17-jdk"
    ensure_dependency "Git" "command -v git" "git" "git"
}


# Sets up the environment for the script to run
setup_environment() {
    export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
    export PATH="${JAVA_HOME}/bin:${PATH}"
    export ANDROID_HOME="${ANDROID_HOME}"
    export PATH="${ANDROID_HOME}/platform-tools:${PATH}"
    echo "sdk.dir=${ANDROID_HOME}" > "${REPO_DIR}/local.properties"
}

# Makes sure client app code is properly set up
initialize_repository() {
    if [[ ! -d "${REPO_DIR}" ]]; then
        echo "Adding Seadroid submodule..."
        git submodule add https://github.com/cy-suite/seadroid.git "${REPO_DIR}"
    elif [[ ! -f "${REPO_DIR}/gradlew" ]]; then
        echo "Repository exists but gradlew missing. Updating submodule..." 
        git submodule update --init --recursive "${REPO_DIR}"
    fi
}

# Starts emulator
start_emulator() {
    "${SCRIPT_DIR}/../../start_emulator.sh" &
    adb wait-for-device
    "${SCRIPT_DIR}/../../check_device.sh"
}

# Waits for emulator to boot
wait_for_boot() {
    echo -n "Waiting for system boot completion..."
    until adb shell getprop sys.boot_completed 2>/dev/null | grep -q "^1$"; do
        sleep 0.5
        echo -n "."
    done
    echo
}

# Waits for desired activity to resume
wait_for_activity() {
    local target_activity="$1"
    echo -n "Waiting for activity ${target_activity}..."
    until adb shell dumpsys activity activities 2>/dev/null | grep -q "mResumedActivity.*${target_activity}"; do
        sleep 0.3
        echo -n "."
    done
    echo
}

# Installs and launches the APK
install_and_launch() {
    # Check to make sure the emulator is running
    if ! adb devices | grep -w "device" | grep -v "List" >/dev/null; then
        echo "ERROR: No Android emulator found."
        echo "Please start the emulator first."
        exit 1
    fi

    # Downlaod the APK if it's not already present
    if [[ ! -f "${APK_PATH}" ]]; then
        download_link="https://github.com/haiwen/seadroid/releases/download/v3.0.16-Release/seafile_3.0.16_patch3.apk"
        curl -L -o "${APK_PATH}" "${download_link}"
    fi

    # Check to make sure it was properly downloaded
    if [[ ! -f "${APK_PATH}" ]]; then
        echo "❌ ERROR: APK not found at ${APK_PATH}"
        exit 1
    fi

    echo "Installing APK: ${APK_PATH}"
    adb install -r "${APK_PATH}"

    # Launch app
    adb shell monkey -p "${SEADROID_PACKAGE}" -c android.intent.category.LAUNCHER 1
    sleep 2

    wait_for_activity "com.seafile.seadroid2/.ui.account.AccountsActivity"
}

# Performs login and server connection on app
connect_to_server() {
    # Get to login screen
    # TODO: Change this to UI automator?
    sleep 5
    adb shell input tap 540 615
    sleep 2

    adb shell input tap 550 420
    sleep 2

    # Fill in login details (server, user, pass)
    adb shell input keyevent KEYCODE_TAB
    sleep 1

    adb shell input keyevent KEYCODE_TAB
    sleep 1

    adb shell input text "${SEAFILE_SITE_URL}"
    sleep 1

    adb shell input keyevent KEYCODE_TAB
    sleep 1

    adb shell input text "${SEAFILE_USER}"
    sleep 1

    adb shell input keyevent KEYCODE_TAB
    sleep 1

    adb shell input keyevent KEYCODE_TAB
    sleep 1

    adb shell input text "${SEAFILE_PASS}"
    sleep 1

    adb shell input keyevent KEYCODE_TAB
    sleep 1

    adb shell input keyevent KEYCODE_TAB
    sleep 1

    adb shell input keyevent KEYCODE_ENTER
    sleep 1
}

main() {
    echo "TESTING!!! Found gradle-wrapper.properties at:"
    find . -name "gradle-wrapper.properties" -type f
    echo "~~~~~~~~~~~~~~~~~~~~~~~~~~~~"
    echo "SEADROID SETUP"
    echo "======================="
    cd "${SCRIPT_DIR}"
    echo "Checking prerequisites..."
    check_prerequisites
    echo "✅ Prerequisites checked."
    echo "======================="
    echo "Initializing repository..."
    initialize_repository
    echo "✅ Repository initialized."
    echo "======================="
    echo "Setting up environment..."
    setup_environment
    echo "✅ Environment set up."
    echo "======================="
    echo "Installing and launching APK..."
    install_and_launch
    echo "✅ APK installed and launched."
    echo "======================="
    echo "Performing login..."
    connect_to_server
    echo "✅ Login complete and connected to server."
    echo "======================="
    echo "Setup complete! Seadroid is ready for testing."
}

main "$@"
