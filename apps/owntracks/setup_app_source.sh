#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_PREFIX="[setup_app_source]"

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
    info "Building OwnTracks Android OSS release APK"
    cd "$SCRIPT_DIR/codebase/project"
    ./gradlew :app:assembleOssRelease
    info "Build completed successfully."
    sign_and_copy_apk
}

sign_and_copy_apk() {
    info "Locating OSS release APK..."
    APK_UNSIGNED=$(find app/build/outputs/apk/oss/release/ -name "*-release-unsigned.apk" -type f 2>/dev/null | head -1)
    if [[ -z "$APK_UNSIGNED" ]]; then
        error "No OSS release APK found. Build may have failed."
    fi
    info "Found unsigned APK: $(basename "$APK_UNSIGNED")"
    
    # Sign the APK with debug keystore
    sign_apk "$APK_UNSIGNED"
    
    # Copy signed APK
    APK_SIGNED="${APK_UNSIGNED/-unsigned.apk/.apk}"
    APK_DIR="$SCRIPT_DIR/apk"
    mkdir -p "$APK_DIR"
    cp "$APK_SIGNED" "$APK_DIR/owntracks.apk"
    info "Copied signed APK to: $APK_DIR/owntracks.apk"
}

sign_apk() {
    local apk_path="$1"
    info "Signing release APK with debug keystore..."
    
    KEYSTORE_FILE="$HOME/.android/debug.keystore"
    
    # Create debug keystore if it doesn't exist
    if [[ ! -f "$KEYSTORE_FILE" ]]; then
        info "Debug keystore not found. Generating a new one..."
        mkdir -p "$HOME/.android/"
        keytool -genkey -v -keystore "$KEYSTORE_FILE" \
            -alias androiddebugkey -keyalg RSA -keysize 2048 \
            -validity 10000 -storepass android -keypass android \
            -dname "CN=Android Debug, O=Android, C=US"
        info "Debug keystore generated at $KEYSTORE_FILE"
    fi
    
    # Find apksigner
    if [[ -z "${ANDROID_HOME:-}" ]]; then
        error "ANDROID_HOME not set, cannot find apksigner"
    fi
    
    APKSIGNER=$(find "$ANDROID_HOME/build-tools" -name apksigner -type f 2>/dev/null | head -1)
    
    if [[ ! -f "$APKSIGNER" ]]; then
        warn "apksigner not found, falling back to jarsigner"
        jarsigner -verbose -sigalg SHA256withRSA -digestalg SHA256 \
            -keystore "$KEYSTORE_FILE" -storepass android -keypass android \
            "$apk_path" androiddebugkey
    else
        info "Using apksigner: $APKSIGNER"
        "$APKSIGNER" sign \
            --ks "$KEYSTORE_FILE" \
            --ks-key-alias androiddebugkey \
            --ks-pass pass:android \
            --key-pass pass:android \
            --v2-signing-enabled true \
            "$apk_path"
    fi
    
    # Rename signed APK
    APK_SIGNED="${apk_path/-unsigned.apk/.apk}"
    mv "$apk_path" "$APK_SIGNED"
    info "Signed APK: $APK_SIGNED"
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

