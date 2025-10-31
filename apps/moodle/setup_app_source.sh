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
    info "Checking prerequisites (Docker)..."
    
    # Check Java
    if ! command -v docker 2>&1; then
        error "Docker not found. Please install Docker"
    fi

    info "Prerequisites verified."
}

setup_environment() {
    info "Setting up build environment. This may take several minutes..."
    
    docker build --platform linux/amd64 -t moodle-builder -f $SCRIPT_DIR/Dockerfile.android .
    info "Environment configured."
}

build_moodle() {
    info "Extract APK"

    docker create --name temp-builder moodle-builder
    mkdir -p apk
    docker cp temp-builder:/moodleapp/platforms/android/app/build/outputs/apk/release/app-release-unsigned.apk ./apk/moodle-unsigned.apk

    echo "Cleaning up Docker containers/images"

    docker rm temp-builder
    docker image rm moodle-builder

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

    APK_UNSIGNED=$(find $SCRIPT_DIR/apk/moodle-unsigned.apk -type f 2>/dev/null | head -1)
    
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

    # Delete unsigned APK if correctly signed
    if [ ! -f ./apk/moodle.apk ]; then
        rm ./apk/moodle-unsigned.apk
        echo "Removed ./apk/moodle-unsigned.apk"
    fi
}

main() {
    info "Moodle Android Setup"
    echo "====================="
    
    CODEBASE_DIR="$SCRIPT_DIR/codebase"
    if [[ ! -d "$CODEBASE_DIR" ]]; then
        error "Moodle codebase directory not found at $CODEBASE_DIR"
    fi
    
    check_prerequisites
    setup_environment
    build_moodle
    
    echo ""
    echo "=========================================="
    info "Moodle Build complete! Moodle is ready to be installed"
    echo "=========================================="
    echo ""
}

main "$@"