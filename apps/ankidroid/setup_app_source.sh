#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

LOG_PREFIX="[setup_app_source]"
LOG_FILE="${SCRIPT_DIR}/setup_app_source.log"
exec > >(tee -a "$LOG_FILE") 2>&1
info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*"; }
error(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*"; exit 1; }

check_prerequisites() {
    info "Checking prerequisites (Java 17 and Android SDK)..."

    if ! command -v java >/dev/null 2>&1; then
        error "Java not found. Please install Java 17."
    fi

    if [ -n "$ANDROID_HOME" ] && [ -d "$ANDROID_HOME" ]; then
      info "Using Android SDK from pre-set ANDROID_HOME: $ANDROID_HOME"
    elif [ -d "${HOME}/Library/Android/sdk" ]; then
      ANDROID_HOME="${HOME}/Library/Android/sdk"
      info "Found Android SDK at: $ANDROID_HOME"
    elif [ -d "${HOME}/Android/Sdk" ]; then
      ANDROID_HOME="${HOME}/Android/Sdk"
      info "Found Android SDK at: $ANDROID_HOME"
    else
      error "Android SDK not found. Please set ANDROID_HOME environment variable."
    fi

    if [[ ! -d "$ANDROID_HOME" ]]; then
        error "Android SDK not found at $ANDROID_HOME"
    fi

    info "Prerequisites verified."
}

setup_environment() {
    info "Setting up build environment..."

    # Set Java 17
    if [[ -d "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home" ]]; then
        export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
    elif [[ -d "/usr/local/Cellar/openjdk@17" ]]; then
        export JAVA_HOME=$(find /usr/local/Cellar/openjdk@17 -name "openjdk.jdk" -type d | head -1)/Contents/Home
    elif [[ -d "/usr/lib/jvm/java-17-openjdk" ]]; then
        export JAVA_HOME=/usr/lib/jvm/java-17-openjdk
    elif command -v /usr/libexec/java_home >/dev/null 2>&1; then
        export JAVA_HOME=$(/usr/libexec/java_home -v 17 2>/dev/null || echo "")
    fi

    if [[ -z "$JAVA_HOME" || ! -d "$JAVA_HOME" ]]; then
        warn "Could not find Java 17 via known paths. Using system default."
        export JAVA_HOME=$(java -XshowSettings:properties -version 2>&1 | grep 'java.home' | awk '{print $3}')
    fi

    export PATH="$JAVA_HOME/bin:$PATH"
    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"

    echo "sdk.dir=$ANDROID_HOME" > "$SCRIPT_DIR/codebase/local.properties"
    info "Environment configured."
    info "Using JAVA_HOME=$JAVA_HOME"
}

get_emulator_arch() {
    if command -v adb >/dev/null 2>&1 && adb get-state >/dev/null 2>&1; then
        local arch
        arch=$(adb shell getprop ro.product.cpu.abi 2>/dev/null | tr -d '\r\n\t ' || echo "")
        if [[ -n "$arch" ]]; then
            info "Detected emulator architecture: $arch" >&2
            echo "$arch"
            return 0
        fi
    fi

    warn "Could not detect emulator architecture, building universal APK" >&2
    echo "universal"
}

build_ankidroid() {
    info "Building AnkiDroid from source (this may take 15-20 minutes)..."

    local arch
    arch=$(get_emulator_arch)

    ./gradlew clean

    info "Building AnkiDroid release APK (with architecture splits for $arch)"
    ./gradlew \
      --no-daemon \
      -Dorg.gradle.java.home="$JAVA_HOME" \
      :AnkiDroid:assembleFullRelease \
      -x lint \
      -x :AnkiDroid:installGitHook

    info "Build completed successfully."
    sign_apk "$arch"
}

sign_apk() {
    local arch="$1"
    info "Signing release APK for $arch architecture (debug keystore)..."

    KEYSTORE_FILE="$HOME/.android/debug.keystore"

    if [ ! -f "$KEYSTORE_FILE" ]; then
        info "Debug keystore not found. Generating a new one..."
        mkdir -p "$HOME/.android/"
        keytool -genkey -v -keystore "$KEYSTORE_FILE" \
                -alias androiddebugkey -keyalg RSA -keysize 2048 \
                -validity 10000 -storepass android -keypass android \
                -dname "CN=Android Debug, O=Android, C=US"
        info "Debug keystore generated at $KEYSTORE_FILE"
    fi

    # Check if APK already signed
    APK_SIGNED=$(find AnkiDroid/build/outputs/apk/full/release/ -name "*$arch*release.apk" -not -name "*unsigned*" -type f 2>/dev/null | head -1)
    if [[ -n "$APK_SIGNED" ]]; then
        info "APK already signed: $(basename "$APK_SIGNED")"
        copy_apk "$APK_SIGNED"
        return 0
    fi

    # Find unsigned APK
    info "Looking for APK with pattern: *$arch*release-unsigned.apk"
    APK_UNSIGNED=$(find AnkiDroid/build/outputs/apk/full/release/ -name "*$arch*release-unsigned.apk" -type f 2>/dev/null | head -1)

    if [[ -z "$APK_UNSIGNED" ]]; then
        warn "No $arch APK found, trying universal APK"
        APK_UNSIGNED=$(find AnkiDroid/build/outputs/apk/full/release/ -name "*universal*release-unsigned.apk" -type f 2>/dev/null | head -1)
    fi

    if [[ -z "$APK_UNSIGNED" ]]; then
        error "No unsigned APK found to sign"
    fi

    info "Signing APK: $APK_UNSIGNED"

    APKSIGNER="$ANDROID_HOME/build-tools/*/apksigner"
    APKSIGNER=$(ls $APKSIGNER 2>/dev/null | head -1)

    if [[ ! -f "$APKSIGNER" ]]; then
        warn "apksigner not found, falling back to jarsigner"
        jarsigner -verbose -sigalg SHA256withRSA -digestalg SHA256 -keystore "$KEYSTORE_FILE" -storepass android -keypass android "$APK_UNSIGNED" androiddebugkey
    else
        info "Using apksigner: $APKSIGNER"
        "$APKSIGNER" sign --ks "$KEYSTORE_FILE" --ks-key-alias androiddebugkey --ks-pass pass:android --key-pass pass:android --v2-signing-enabled true "$APK_UNSIGNED"
    fi

    APK_SIGNED="${APK_UNSIGNED/-unsigned.apk/.apk}"
    mv "$APK_UNSIGNED" "$APK_SIGNED"

    info "Signed APK: $APK_SIGNED"
    copy_apk "$APK_SIGNED"
}

copy_apk() {
    local apk_path="$1"
    APK_DIR="$SCRIPT_DIR/apk"
    mkdir -p "$APK_DIR"
    cp -f "$apk_path" "$APK_DIR/ankidroid.apk"
    info "Copied to: $APK_DIR/ankidroid.apk"
}

main() {
    info "AnkiDroid Android Setup"
    echo "============================"

    CODEBASE_DIR="$SCRIPT_DIR/codebase"
    if [[ ! -d "$CODEBASE_DIR" ]]; then
        error "AnkiDroid codebase directory not found at $CODEBASE_DIR"
    fi

    cd "$CODEBASE_DIR"

    if [[ ! -f "gradlew" ]]; then
        error "gradlew not found in codebase directory."
    fi

    check_prerequisites
    setup_environment
    build_ankidroid

    echo ""
    echo "=========================================="
    info "AnkiDroid Build complete! AnkiDroid is ready to be installed"
    echo "=========================================="
    echo ""
}

main "$@"