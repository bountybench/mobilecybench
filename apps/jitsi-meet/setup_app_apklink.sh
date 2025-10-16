#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
ANDROID_HOME="${HOME}/.android-sdk"
source "$ROOT_DIR/utils/android.sh" || true
: "${AVD_NAME:=Pixel_2_API_28}"

check_prerequisites() {
    cd codebase/android
    
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

    export ANDROID_HOME="$ANDROID_HOME"
    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"

    echo "sdk.dir=$ANDROID_HOME" > local.properties

    echo "Environment configured."
}

download_jitsi_to_local() {
    
    #ALL THE BUILD COMMANDS ARE PLACED HERE AS A PLACEHOLDER (FUTURE USE WHEN RELEASE BUILD APKS CAN BE CACHED)
    #echo "Building Jitsi Meet Android from source..."
    #echo "This may take several minutes..."

    #if grep -q "MaxPermSize" gradle.properties; then
    #    sed -i 's/-XX:MaxPermSize=[^ ]*//g' gradle.properties
    #    echo "Ensured MaxPermSize configuration in gradle properties..."
    #fi

    #echo "Starting build..."
    #./gradlew assembleRelease --stacktrace --warning-mode=all 2>&1 | tee build.log
    #./gradlew :sdk:bundleReleaseJsAndAssets --info
    #./gradlew assembleDebug
    #prebuilt
    #echo "Build completed successfully."

    cd ../..
    ls
    echo "Downloading prebuilt Jitsi Meet APK..."
    local APK_URL="https://f-droid.org/F-Droid.apk"
    local DEST_DIR="apk/app-prebuilt.apk"

    mkdir "apk"
    echo "Downloading from: $APK_URL"
    curl -L --fail --retry 3 --retry-connrefused -o "$DEST_DIR" "$APK_URL"

    if [[ ! -f "$DEST_DIR" ]]; then
        echo "ERROR: Download failed. APK file not found."
        exit 1
    fi

    echo "Successfully downloaded prebuilt Jitsi Meet APK:"
    echo "$DEST_DIR"
    
}

main() {
    echo "Jitsi Meet Android Setup"

    echo "Making setup.sh files executable"
    chmod +x ./setup.sh
    chmod +x ./cleanup.sh
    chmod +x ../../setup.sh
    chmod +x ./vuln_scenarios/vuln_scenario_0/vuln.sh
    chmod +x ./vuln_scenarios/vuln_scenario_1/vuln.sh

    npm uninstall -g react-native-cli @react-native-community/cli || true

    check_prerequisites
    setup_environment
    download_jitsi_to_local

    echo ""
    echo "Setup complete! Jitsi Meet Android is ready to launch."
}

main "$@"