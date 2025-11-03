#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_PREFIX="[setup_app_source]"
LOG_FILE="${SCRIPT_DIR}/setup_app_source.log"
exec > >(tee -a "$LOG_FILE") 2>&1
info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*"; }
error(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*"; exit 1; }

check_prerequisites() {
    info "Checking prerequisites (Java and Android SDK)..."
    if ! command -v java >/dev/null 2>&1; then
        error "Java not found. Please install Java 21."
    fi

    if [[ -n "${ANDROID_HOME:-}" ]]; then
        info "Using Android SDK from pre-set ANDROID_HOME: $ANDROID_HOME"
    elif [[ -d "$HOME/Library/Android/sdk" ]]; then
        export ANDROID_HOME="$HOME/Library/Android/sdk"
        info "Found Android SDK at $ANDROID_HOME"
    elif [[ -d "$HOME/.android-sdk" ]]; then
        export ANDROID_HOME="$HOME/.android-sdk"
        info "Found Android SDK at $ANDROID_HOME"
    elif [[ -d "$HOME/Android/Sdk" ]]; then
        export ANDROID_HOME="$HOME/Android/Sdk"
        info "Found Android SDK at $ANDROID_HOME"
    else
        error "Android SDK not found. Please set ANDROID_HOME or install Android SDK."
    fi

    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
    info "Prerequisites verified."
}

setup_environment() {
    info "Setting up build environment..."
    # Set Java 21 (required for OwnTracks Gradle build)
    if [[ -d "/opt/homebrew/opt/openjdk@21" ]]; then
        export JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home
    elif [[ -d "/usr/lib/jvm/java-21-openjdk" ]]; then
        export JAVA_HOME=/usr/lib/jvm/java-21-openjdk
    elif command -v /usr/libexec/java_home &>/dev/null; then
        export JAVA_HOME="$(/usr/libexec/java_home -v 21)"
    else
        warn "Could not find Java 21 via known paths. Using system default."
        export JAVA_HOME=$(java -XshowSettings:properties -version 2>&1 | grep 'java.home' | awk '{print $3}')
    fi
    export PATH="$JAVA_HOME/bin:$PATH"

    # Set Android SDK
    echo "sdk.dir=$ANDROID_HOME" > "$SCRIPT_DIR/codebase/project/local.properties"
    info "Environment configured."
}

build_owntracks() {
    info "Building OwnTracks from source (this may take several minutes)..."
    info "Building OwnTracks Android OSS debug APK"
    cd "$SCRIPT_DIR/codebase/project"
    ./gradlew :app:assembleOssDebug
    info "Build completed successfully."
    copy_debug_apk
}

copy_debug_apk() {
    info "Locating OSS debug APK..."
    APK_DEBUG=$(find app/build/outputs/apk/oss/debug/ -name "*debug.apk" -type f 2>/dev/null | head -1)
    if [[ -z "$APK_DEBUG" ]]; then
        error "No OSS debug APK found. Build may have failed."
    fi
    info "Found APK: $(basename "$APK_DEBUG")"
    APK_DIR="$SCRIPT_DIR/apk"
    mkdir -p "$APK_DIR"
    cp "$APK_DEBUG" "$APK_DIR/owntracks.apk"
    info "Copied to: $APK_DIR/owntracks.apk"
}

main() {
    info "OwnTracks Android Setup"
    echo "============================"
    CODEBASE_DIR="$SCRIPT_DIR/codebase"
    if [[ ! -d "$CODEBASE_DIR" ]]; then
        error "OwnTracks codebase directory not found at $CODEBASE_DIR"
    fi

    check_prerequisites
    setup_environment
    build_owntracks

    echo ""
    echo "=========================================="
    info "OwnTracks Build complete! OwnTracks is ready to be installed"
    echo "=========================================="
    echo ""
}
main "$@"

