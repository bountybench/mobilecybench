#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$SCRIPT_DIR/build_moodle_app.log"
exec > >(tee -a "$LOG_FILE") 2>&1

LOG_PREFIX="[moodleapp]"
info() { echo "$LOG_PREFIX $*"; }
error() { echo "$LOG_PREFIX [error] $*" >&2; exit 1; }

check_prerequisites() {
    info "Checking prerequisites..."

    if ! command -v node >/dev/null 2>&1; then
        error "Node.js not found. Install Node 18+."
    fi

    if ! command -v npm >/dev/null 2>&1; then
        error "npm not found. Install npm."
    fi

    if ! command -v java >/dev/null 2>&1; then
        error "Java not found. Install Java 17."
    fi

    if [[ -z "$ANDROID_HOME" || ! -d "$ANDROID_HOME" ]]; then
        error "ANDROID_HOME not set or Android SDK missing. Please export ANDROID_HOME."
    fi

    info "All prerequisites satisfied."
}

setup_environment() {
    info "Setting up environment..."
    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"

    # Ensure sdk.dir exists for Cordova
    echo "sdk.dir=$ANDROID_HOME" > "$SCRIPT_DIR/local.properties"

    # Install dependencies
    info "Installing npm dependencies..."
    npm ci

    info "Building production web assets..."
    npm run build:prod

    info "Environment setup complete."
}

build_apk() {
    info "Starting Moodle App APK build..."

    # Navigate to Cordova project folder
    if [[ ! -d "cordova" ]]; then
        error "Cordova project folder not found. Run from moodleapp root."
    fi
    cd cordova

    # Install Cordova dependencies
    info "Installing Cordova dependencies..."
    npm ci

    # Ensure Cordova platform is set
    if ! npx cordova platform ls | grep -q android; then
        info "Adding Android platform..."
        npx cordova platform add android
    fi

    # Build the APK
    info "Running Cordova build..."
    NODE_ENV=production npx cordova build android --release

    APK_PATH=$(find platforms/android/app/build/outputs/apk/release -name "*.apk" | head -1)
    if [[ -z "$APK_PATH" ]]; then
        error "Build failed, no APK found."
    fi

    OUTPUT_DIR="$SCRIPT_DIR/apk"
    mkdir -p "$OUTPUT_DIR"
    cp "$APK_PATH" "$OUTPUT_DIR/"
    info "APK copied to $OUTPUT_DIR/"
}

sign_apk() {
    info "Signing APK with debug keystore..."
    KEYSTORE="$HOME/.android/debug.keystore"

    if [ ! -f "$KEYSTORE" ]; then
        info "Generating debug keystore..."
        mkdir -p "$HOME/.android"
        keytool -genkey -v -keystore "$KEYSTORE" \
            -alias androiddebugkey -keyalg RSA -keysize 2048 \
            -validity 10000 -storepass android -keypass android \
            -dname "CN=Android Debug,O=Android,C=US"
    fi

    APK_PATH=$(find "$SCRIPT_DIR/apk" -name "*.apk" | head -1)
    if [[ -z "$APK_PATH" ]]; then
        error "No APK found to sign."
    fi

    APKSIGNER=$(find "$ANDROID_HOME/build-tools" -name apksigner -type f | head -1)
    if [[ -z "$APKSIGNER" ]]; then
        error "apksigner not found in Android SDK."
    fi

    "$APKSIGNER" sign \
        --ks "$KEYSTORE" \
        --ks-key-alias androiddebugkey \
        --ks-pass pass:android \
        --key-pass pass:android \
        "$APK_PATH"

    info "Signed APK: $APK_PATH"
}

main() {
    info "=============================="
    info "Moodle App Build Script"
    info "=============================="

    cd "$SCRIPT_DIR"
    check_prerequisites
    setup_environment
    build_apk
    sign_apk

    info "=========================================="
    info "✅ Moodle App build complete! APK is ready."
    info "=========================================="
}

main "$@"

