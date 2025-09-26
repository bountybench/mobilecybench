#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
ANDROID_HOME="${HOME}/.android-sdk"
source "$ROOT_DIR/utils/android.sh" || true
: "${AVD_NAME:=Pixel_2_API_28}"

check_prerequisites() {
    echo "Checking prerequisites..."

    if ! command -v java >/dev/null 2>&1; then
        echo "ERROR: Java not found. Please install Java 17."
        exit 1
    fi

    if [[ ! -d "$ANDROID_HOME" && -d "/usr/local/lib/android/sdk" ]]; then
        ANDROID_HOME="/usr/local/lib/android/sdk"
    fi

    if [[ ! -d "$ANDROID_HOME" ]]; then
        echo "ERROR: Android SDK not found at $ANDROID_HOME"
        echo "Please run the Android emulator setup first."
        exit 1
    fi

    echo "Prerequisites verified."
}

setup_environment() {
    echo "Setting up build environment..."

    export JAVA_HOME=/usr/lib/jvm/temurin-17-jdk-amd64
    export PATH="$JAVA_HOME/bin:$PATH"

    export ANDROID_HOME="$ANDROID_HOME"
    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"

    echo "sdk.dir=$ANDROID_HOME" > local.properties

    echo "Environment configured."
}

build_jitsi() {
    
    echo "Building Jitsi Meet Android from source..."
    echo "This may take several minutes..."

    if grep -q "MaxPermSize" gradle.properties; then
        sed -i 's/-XX:MaxPermSize=[^ ]*//g' gradle.properties
    fi
    ./gradlew assembleDebug


    echo "Build completed successfully."
    
}

main() {
    echo "Jitsi Meet Android Setup"

    echo "Making setup.sh files executable"
    chmod +x ./setup.sh
    chmod +x ./cleanup.sh
    chmod +x ./run_checks.sh
    chmod +x ../../setup.sh
    chmod +x ./vuln_scenarios/vuln_scenario_0/vuln.sh
    chmod +x ./vuln_scenarios/vuln_scenario_1/vuln.sh

    npm uninstall -g react-native-cli @react-native-community/cli || true

    cd codebase
    yarn install

    echo "Starting Metro bundler in the background..."
    nohup npx react-native start --reset-cache > metro.log 2>&1 &
    echo "Finished installing packages."

    cd android
    check_prerequisites
    setup_environment

    echo ""
    echo "Setup complete! Jitsi Meet Android is ready to launch."
}

main "$@"
