#!/usr/bin/env bash
set -e  # Stop script on error

# General variables
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="seadroid"

# Android SDK variables
ANDROID_HOME="${HOME}/.android-sdk"
AVD_NAME="Pixel_2_API_28"   

# Function to dynamically find the most recent APK file
get_apk_path() {
    local apk_dir="${REPO_DIR}/app/build/outputs/apk/release"
    
    # Check if the directory exists
    if [[ ! -d "${apk_dir}" ]]; then
        echo "❌ ERROR: APK output directory not found at ${apk_dir}"
        echo "Make sure the app has been built first."
        return 1
    fi
    
    # Find all APK files matching the pattern and get the one with the highest patch number
    local latest_apk
    latest_apk=$(find "${apk_dir}" -name "seafile_3.0.16_patch*.apk" -type f | \
                 sort -V | tail -n1)
    
    if [[ -z "${latest_apk}" ]]; then
        echo "❌ ERROR: No APK files matching pattern 'seafile_3.0.16_patch*.apk' found in ${apk_dir}"
        return 1
    fi
    
    # Return relative path from the repo directory
    echo "${latest_apk#${REPO_DIR}/}"
}

# Set APK path dynamically
APK_REL="app/build/outputs/apk/debug/seafile-debug-3.0.16.apk"  # Set to debug by default
APK_PATH="${REPO_DIR}/${APK_REL}"
USE_RELEASE_APK=false

# Seafile variables
SEAFILE_SITE_URL="10.0.2.2:8000"
SEAFILE_USER="anarchist@example.com"   # Logging in as normal user
SEAFILE_PASS="zU72wO7eX4UZ"
# SEAFILE_ACCOUNT_ACTIVITY="com.seafile.seadroid2.debug/com.seafile.seadroid2.ui.account.AccountsActivity"    # Not exported, for some reason
BASIC_ACTIVITY="com.android.launcher3/com.android.launcher3.Launcher"


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

    if [[ ! -d "${ANDROID_HOME}" ]]; then
        echo "❌ ERROR: Android SDK not found at ${ANDROID_HOME}. Please make sure to run setup.sh first."
        echo "For reference, here are the steps to install the Android SDK manually:"
        echo "  1. Download the command-line tools. E.g. curl -L \"https://dl.google.com/android/repository/commandlinetools-mac-11076708_latest.zip\" -o cmdline-tools.zip"
        echo "  2. Create the directory: mkdir -p ${ANDROID_HOME}"
        echo "  3. Extract the downloaded zip file into that directory. E.g. unzip cmdline-tools.zip | mv cmdline-tools/* ${ANDROID_HOME}/cmdline-tools/latest/"
        echo "  Recommended: Add sdkmanager tool to your PATH. E.g. export PATH=\"${ANDROID_HOME}/cmdline-tools/latest/bin:${PATH}\""
        echo "  4. Accept licenses: sdkmanager --licenses"
        exit 1
    else
        echo "✅ Android SDK is installed."
    fi

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
        git submodule add https://github.com/haiwen/seadroid.git "${REPO_DIR}"
    elif [[ ! -f "${REPO_DIR}/gradlew" ]]; then
        echo "Repository exists but gradlew missing. Updating submodule..." 
        git submodule update --init --recursive "${REPO_DIR}"
    fi
}

# Builds the Seadroid APK according to instructions: https://github.com/haiwen/seadroid/tree/master#README.md
build_seadroid() {

    pushd "${REPO_DIR}" >/dev/null

    # Alter key properties to desired setup
    if [[ ! -f "./app/key.properties" ]]; then
        mv ./app/key.properties.example ./app/key.properties
    fi
    
    # Create keystore
    if [[ ! -f "./app/debug.keystore" ]]; then
        keytool -genkey -v -keystore app/debug.keystore -alias AndroidDebugKey -keyalg RSA -keysize 2048 -validity 1 -storepass android -keypass android -dname "cn=TEST, ou=TEST, o=TEST, c=TE"
    fi

    # Make sure gradlew is executable
    chmod +x gradlew

    # Build the APK
    if [[ "${USE_RELEASE_APK}" == true ]]; then
        ./gradlew assembleRelease
    else
        ./gradlew assembleDebug
    fi

    popd >/dev/null
}

# Starts emulator
start_emulator() {
    "${SCRIPT_DIR}/../start_emulator.sh" &
    adb wait-for-device
    "${SCRIPT_DIR}/../check_device.sh"
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
    # Re-determine APK path if it wasn't set initially (e.g., after building)
    if [[ -z "${APK_REL}" && "${USE_RELEASE_APK}" == true ]]; then
        APK_REL=$(get_apk_path)
        if [[ $? -ne 0 ]]; then
            echo "❌ ERROR: Still cannot determine APK path after build."
            exit 1
        fi
        APK_PATH="${REPO_DIR}/${APK_REL}"
        echo "Found APK: ${APK_PATH}"
    fi

    if [[ ! -f "${APK_PATH}" ]]; then
        echo "❌ ERROR: APK not found at ${APK_PATH}"
        exit 1
    fi

    echo "Installing APK: ${APK_PATH}"
    adb install -r "${APK_PATH}"

    # adb shell am start \
    # -n ${SEAFILE_ACCOUNT_ACTIVITY}

    adb shell am start \
    -n ${BASIC_ACTIVITY}
}

# Performs login and server connection on app
connect_to_server() {
    # wait_for_activity "AccountsActivity"
    wait_for_activity "Launcher"

    # Get to login screen
    sleep 3
    adb shell input swipe 500 1600 500 500
    sleep 1

    adb shell input tap 750 900
    sleep 10

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
    echo "Building Seadroid APK..."
    build_seadroid
    echo "✅ Seadroid APK built."
    echo "======================="
    echo "Starting emulator..."
    start_emulator
    echo "Waiting for emulator to boot..."
    wait_for_boot
    echo "✅ Emulator booted."
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
