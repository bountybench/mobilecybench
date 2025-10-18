#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

LOG_PREFIX="[setup_app_source]"
LOG_FILE="${SCRIPT_DIR}/setup_app_source.log"
# Duplicate outputs to console and log file
exec > >(tee -a "$LOG_FILE") 2>&1
info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*"; }
error(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*"; exit 1; }

check_prerequisites() {
    info "Checking prerequisites (Java and Android SDK)..."

    # Check Java
    if ! command -v java >/dev/null 2>&1; then
        error "Java not found. Please install Java 17."
    fi

    # More robust check for the Android SDK path.
    if [ -n "$ANDROID_HOME" ] && [ -d "$ANDROID_HOME" ]; then
      info "Using Android SDK from pre-set ANDROID_HOME: $ANDROID_HOME"
    elif [ -d "${HOME}/.android-sdk" ]; then
      # Fallback to the default path if ANDROID_HOME isn't set.
      ANDROID_HOME="${HOME}/.android-sdk"
      info "Found Android SDK at default location: $ANDROID_HOME"
    else
      error "Android SDK not found. Please set the ANDROID_HOME environment variable."
    fi


    # Check Android SDK
    if [[ ! -d "$ANDROID_HOME" ]]; then
        error "Android SDK not found at $ANDROID_HOME. Please run the Android emulator setup first."
    fi

    info "Prerequisites verified."
}

setup_environment() {
    info "Setting up build environment..."

    # Try macOS helper first, then Homebrew, then Linux paths
    if command -v /usr/libexec/java_home >/dev/null 2>&1; then
        JAVA_17_HOME="$(/usr/libexec/java_home -v 17 2>/dev/null || true)"
        if [[ -n "$JAVA_17_HOME" ]]; then
            export JAVA_HOME="$JAVA_17_HOME"
        fi
    fi

    # If not found via java_home, try common paths
    if [[ -z "$JAVA_HOME" ]]; then
        if [[ -d "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home" ]]; then
            export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
        elif [[ -d "/usr/lib/jvm/java-17-openjdk" ]]; then
            export JAVA_HOME=/usr/lib/jvm/java-17-openjdk
        else
            warn "Java 17 not found at standard locations, using system Java"
            export JAVA_HOME=$(java -XshowSettings:properties -version 2>&1 | grep 'java.home' | awk '{print $3}')
        fi
    fi

    export PATH="$JAVA_HOME/bin:$PATH"
    info "Using Java at: $JAVA_HOME"

    # Set Android SDK
    export ANDROID_HOME="$ANDROID_HOME"
    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"

    # Create local.properties for Jerboa build (in codebase directory)
    echo "sdk.dir=$ANDROID_HOME" > "$SCRIPT_DIR/codebase/local.properties"
    info "Environment configured."
}

build_jerboa() {
    info "Building Jerboa from source (this may take several minutes)..."

    ./gradlew clean
    ./gradlew :app:assembleRelease

    info "Build completed successfully."
    sign_apk
}

# Sign the release APK with debug keystore
sign_apk() {
    info "Signing release APK (debug keystore)..."

    KEYSTORE_FILE="$HOME/.android/debug.keystore"

    # Check if the debug keystore exists, and create it if it doesn't.
    if [ ! -f "$KEYSTORE_FILE" ]; then
        info "Debug keystore not found. Generating a new one..."
        mkdir -p "$HOME/.android/"
        keytool -genkey -v -keystore "$KEYSTORE_FILE" \
                -alias androiddebugkey -keyalg RSA -keysize 2048 \
                -validity 10000 -storepass android -keypass android \
                -dname "CN=Android Debug, O=Android, C=US"
        info "Debug keystore generated at $KEYSTORE_FILE"
    fi

    # Find unsigned APK to sign
    APK_UNSIGNED=$(find app/build/outputs/apk/release/ -name "*release-unsigned.apk" -type f 2>/dev/null | head -1)

    if [[ -z "$APK_UNSIGNED" ]]; then
        # Try to find already signed APK
        APK_SIGNED=$(find app/build/outputs/apk/release/ -name "*release.apk" -not -name "*unsigned*" -type f 2>/dev/null | head -1)
        if [[ -n "$APK_SIGNED" ]]; then
            info "APK already signed: $(basename "$APK_SIGNED")"
            copy_apk "$APK_SIGNED"
            return 0
        fi
        error "No unsigned APK found to sign"
    fi

    info "Signing APK: $APK_UNSIGNED"

    # Use apksigner instead of deprecated jarsigner
    if [[ -z "$ANDROID_HOME" ]]; then
        error "ANDROID_HOME not set, cannot find apksigner"
    fi

    APKSIGNER="$ANDROID_HOME/build-tools/*/apksigner"
    APKSIGNER=$(ls $APKSIGNER 2>/dev/null | head -1)

    if [[ ! -f "$APKSIGNER" ]]; then
        warn "apksigner not found, falling back to jarsigner"
        jarsigner -verbose -sigalg SHA256withRSA -digestalg SHA256 -keystore "$HOME/.android/debug.keystore" -storepass android -keypass android "$APK_UNSIGNED" androiddebugkey
    else
        info "Using apksigner: $APKSIGNER"
        "$APKSIGNER" sign --ks "$HOME/.android/debug.keystore" --ks-key-alias androiddebugkey --ks-pass pass:android --key-pass pass:android --v2-signing-enabled true "$APK_UNSIGNED"
    fi

    APK_SIGNED="${APK_UNSIGNED/-unsigned.apk/.apk}"
    mv "$APK_UNSIGNED" "$APK_SIGNED"

    info "Signed APK: $APK_SIGNED"
    copy_apk "$APK_SIGNED"
}

copy_apk() {
    local APK_SIGNED="$1"

    # Copy signed APK to standard location
    APK_DIR="$SCRIPT_DIR/apk"
    mkdir -p "$APK_DIR"
    cp "$APK_SIGNED" "$APK_DIR/jerboa.apk"

    info "Copied to: $APK_DIR/jerboa.apk"
}

main() {
    info "Jerboa Android Setup"
    echo "============================"

    CODEBASE_DIR="$SCRIPT_DIR/codebase"
    if [[ ! -d "$CODEBASE_DIR" ]]; then
        error "Jerboa codebase directory not found at $CODEBASE_DIR"
    fi

    cd "$CODEBASE_DIR"

    if [[ ! -f "gradlew" ]]; then
        error "gradlew not found in codebase directory."
    fi

    check_prerequisites
    setup_environment
    build_jerboa

    echo ""
    echo "=========================================="
    info "Jerboa Build complete! Jerboa is ready to be installed"
    echo "=========================================="
    echo ""
}

main "$@"