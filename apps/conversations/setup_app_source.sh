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
    
    # Create local.properties for Conversations build (in codebase directory)
    echo "sdk.dir=$ANDROID_HOME" > "$SCRIPT_DIR/codebase/local.properties"
    info "Environment configured."
}

build_conversations() {
    info "Building Conversations from source (this may take several minutes)..."

    local arch="universal"

    ./gradlew clean

    # Build all architectures - Android will create splits automatically
    info "Building Conversations (with universal APK)"
    ./gradlew assembleConversationsFreeRelease

    info "Build completed successfully."
    sign_apk "$arch"
}

# Sign the release APK with debug keystore
sign_apk() {
    local arch="$1"
    info "Signing release APK for $arch architecture (debug keystore)..."

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

    # Check if architecture-specific APK already signed
    APK_SIGNED=$(find build/outputs/apk/conversationsFree/release/ -name "*conversations-free*$arch*release.apk" -not -name "*unsigned*" -type f 2>/dev/null | head -1)
    if [[ -n "$APK_SIGNED" ]]; then
        info "APK already signed: $(basename "$APK_SIGNED")"
        return 0
    fi

    # Find unsigned APK to sign (prefer architecture-specific, fallback to universal)
    info "Looking for APK with pattern: *conversations-free*$arch*release-unsigned.apk"
    APK_UNSIGNED=$(find build/outputs/apk/conversationsFree/release/ -name "*conversations-free*$arch*release-unsigned.apk" -type f 2>/dev/null | head -1)

    if [[ -z "$APK_UNSIGNED" ]]; then
        warn "No $arch APK found, trying universal APK"
        APK_UNSIGNED=$(find build/outputs/apk/conversationsFree/release/ -name "*conversations-free*universal*release-unsigned.apk" -type f 2>/dev/null | head -1)
    else
        info "Found architecture-specific APK: $APK_UNSIGNED"
    fi
    
    if [[ -z "$APK_UNSIGNED" ]]; then
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

    # Copy signed APK to standard location
    APK_DIR="$SCRIPT_DIR/apk"
    mkdir -p "$APK_DIR"
    APK_NAME=$(basename "$APK_SIGNED")
    cp "$APK_SIGNED" "$APK_DIR/$APK_NAME"

    # Rename to conversations.apk
    mv "$APK_DIR/$APK_NAME" "$APK_DIR/conversations.apk"

    info "Signed APK: $APK_SIGNED"
    info "Copied to: $APK_DIR/conversations.apk"
}


main() {
    info "Conversations Android Setup"
    echo "============================"
    
    CODEBASE_DIR="$SCRIPT_DIR/codebase"
    if [[ ! -d "$CODEBASE_DIR" ]]; then
        error "Conversations codebase directory not found at $CODEBASE_DIR"
    fi
    
    cd "$CODEBASE_DIR"
    
    if [[ ! -f "gradlew" ]]; then
        error "gradlew not found in codebase directory."
    fi
    
    check_prerequisites
    setup_environment
    build_conversations
    
    echo ""
    echo "=========================================="
    info "Conversations Build complete! Conversations is ready to be installed"
    echo "=========================================="
    echo ""
}

main "$@"