#!/usr/bin/env bash
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

    # Set Java 17
    if [[ -d "/opt/homebrew/opt/openjdk@17" ]]; then
        export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
    elif [[ -d "/usr/lib/jvm/java-17-openjdk" ]]; then
        export JAVA_HOME=/usr/lib/jvm/java-17-openjdk
    else
        warn "Could not find Java 17 via known paths. Using system default."
        export JAVA_HOME=$(java -XshowSettings:properties -version 2>&1 | grep 'java.home' | awk '{print $3}')
    fi

    export PATH="$JAVA_HOME/bin:$PATH"

    # Set Android SDK
    export ANDROID_HOME="$ANDROID_HOME"
    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"

    # Create local.properties for moememos build (in codebase directory)
    echo "sdk.dir=$ANDROID_HOME" > "$SCRIPT_DIR/codebase/local.properties"
    info "Environment configured."
}

build_moememos() {
    info "Building MoeMemos from source..."
    git submodule update --init --recursive

    ./gradlew clean
    ./gradlew assembleRelease
    info "Build completed successfully."
    sign_apk
}

# Sign the release APK with debug keystore using modern APK signing
sign_apk() {
    info "Signing release APK (debug keystore with v2+ signature scheme)..."

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

    APK_UNSIGNED=$(find app/build/outputs/apk/release/ -name "*-release-unsigned.apk" -type f 2>/dev/null | head -1)

    if [[ -z "$APK_UNSIGNED" ]]; then
        warn "No unsigned release APK found to sign."
        return 1
    fi

    APK_SIGNED="${APK_UNSIGNED/-unsigned.apk/.apk}"

    # Use apksigner for SDK 30+ compatibility (supports v2+ signature schemes)
    local apksigner_path="$ANDROID_HOME/build-tools"
    local apksigner_tool=""

    # Find the latest build-tools version that has apksigner
    if [[ -d "$apksigner_path" ]]; then
        local latest_build_tools
        latest_build_tools=$(ls -1 "$apksigner_path" | grep -E '^[0-9]+\.[0-9]+\.[0-9]+' | sort -V | tail -1)
        if [[ -n "$latest_build_tools" && -f "$apksigner_path/$latest_build_tools/apksigner" ]]; then
            apksigner_tool="$apksigner_path/$latest_build_tools/apksigner"
            info "Using apksigner from build-tools $latest_build_tools"
        fi
    fi

    if [[ -n "$apksigner_tool" && -x "$apksigner_tool" ]]; then
        info "Signing with apksigner (v1+v2 schemes for SDK 30+ compatibility)"
        "$apksigner_tool" sign \
            --ks "$KEYSTORE_FILE" \
            --ks-key-alias androiddebugkey \
            --ks-pass pass:android \
            --key-pass pass:android \
            --v1-signing-enabled true \
            --v2-signing-enabled true \
            --out "$APK_SIGNED" \
            "$APK_UNSIGNED"
    else
        error "apksigner not found. Required for SDK 30+ compatibility. Please ensure Android build-tools are properly installed."
    fi

    info "Signed APK: $APK_SIGNED"

    # Verify the signature
    if [[ -n "$apksigner_tool" && -x "$apksigner_tool" ]]; then
        info "Verifying APK signature..."
        if "$apksigner_tool" verify "$APK_SIGNED"; then
            info "APK signature verification successful"
        else
            warn "APK signature verification failed"
        fi
    fi
}


# Copy the signed APK to SCRIPT_DIR/apk/moememos.apk (overwrite if exists)
copy_apk() {
    info "Copying signed APK to ${SCRIPT_DIR}/apk/moememos.apk"

    local apk_dir="${SCRIPT_DIR}/apk"
    local target_apk="${apk_dir}/moememos.apk"
    local source_apk="$APK_SIGNED"

    # Strictly rely on APK_SIGNED from sign_apk()
    if [[ -z "${source_apk}" || ! -f "${source_apk}" ]]; then
        error "Signed APK not available. Ensure sign_apk() completed successfully."
    fi

    mkdir -p "$apk_dir"
    cp -f "$source_apk" "$target_apk"
    info "APK copied to: $target_apk"
}



main() {
    info "MoeMemos Android Setup"
    echo "====================="

    CODEBASE_DIR="$SCRIPT_DIR/codebase"
    if [[ ! -d "$CODEBASE_DIR" ]]; then
        error "MoeMemos codebase directory not found at $CODEBASE_DIR"
    fi

    cd "$CODEBASE_DIR"

    if [[ ! -f "gradlew" ]]; then
        error "gradlew not found in codebase directory."
    fi

    check_prerequisites
    setup_environment
    build_moememos
    copy_apk

    echo ""
    echo "=========================================="
    info "MoeMemos Build complete! MoeMemos is ready to be installed"
    echo "=========================================="
    echo ""
}

main "$@"
