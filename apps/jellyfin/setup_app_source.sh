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

apply_update_patch() {
    info "Applying gradle update patch..."

    # Reset codebase submodule to clean state first
    cd "$CODEBASE_DIR"
    git reset --hard HEAD
    git clean -fd
    cd ..

    if [[ -f "$SCRIPT_DIR/jellyfin-gradle-update.patch" ]]; then
        # Apply patch from parent directory to codebase (stay in parent dir for correct paths)
        if patch -p0 -d "$CODEBASE_DIR" < "$SCRIPT_DIR/jellyfin-gradle-update.patch"; then
            info "Patch applied successfully"
        else
            error "Failed to apply patch"
        fi
    else
        error "Patch file not found: $SCRIPT_DIR/jellyfin-gradle-update.patch"
    fi
}

ensure_java_compatibility() {
    info "Ensuring Java compatibility for Jellyfin build"

    # Check if we have a compatible Java version (8, 11, or 17)
    local java_version=""
    if command -v java >/dev/null 2>&1; then
        java_version=$(java -version 2>&1 | head -n 1 | sed 's/.*version "\([^"]*\)".*/\1/' | cut -d. -f1-2)
        info "Current Java version: $java_version"
    fi

    # Check if current Java is compatible (version 8, 11, or 17)
    case "$java_version" in
        "1.8"|"8"|"11"|"17")
            info "Java $java_version is compatible"
            return 0
            ;;
        *)
            info "Java $java_version detected. Will use compatible Java from available versions."
            return 0
            ;;
    esac

}

check_prerequisites() {
    info "Checking prerequisites (Java and Android SDK)..."

    # Ensure compatible Java version is installed
    ensure_java_compatibility

    # Check Java again after potential installation
    if ! command -v java >/dev/null 2>&1; then
        error "Java not found even after installation attempt. Please install Java 8, 11, or 17 manually."
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

    # Try to find compatible Java version (Java 8, 11, or 17)
    JAVA_CANDIDATES=(
        "/opt/homebrew/opt/openjdk@11/libexec/openjdk.jdk/Contents/Home"
        "/opt/homebrew/opt/openjdk@8/libexec/openjdk.jdk/Contents/Home"
        "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"
        "/usr/lib/jvm/java-11-openjdk"
        "/usr/lib/jvm/java-8-openjdk"
        "/usr/lib/jvm/java-17-openjdk"
        "/opt/local/Library/Java/JavaVirtualMachines/jdk-11-azul-zulu.jdk/Contents/Home"
        "/opt/local/Library/Java/JavaVirtualMachines/jdk-8-azul-zulu.jdk/Contents/Home"
        "/opt/local/Library/Java/JavaVirtualMachines/jdk-17-azul-zulu.jdk/Contents/Home"
        "/opt/local/Library/Java/JavaVirtualMachines/openjdk11/Contents/Home"
        "/opt/local/Library/Java/JavaVirtualMachines/openjdk8/Contents/Home"
    )

    # Also check /usr/libexec/java_home for macOS
    if command -v /usr/libexec/java_home >/dev/null 2>&1; then
        # Try to get Java 11 first, then 8, then 17
        for version in 11 8 17; do
            if java_home=$(/usr/libexec/java_home -v $version 2>/dev/null); then
                JAVA_CANDIDATES=("$java_home" "${JAVA_CANDIDATES[@]}")
                break
            fi
        done
    fi

    JAVA_HOME=""
    for candidate in "${JAVA_CANDIDATES[@]}"; do
        if [[ -d "$candidate" ]]; then
            export JAVA_HOME="$candidate"
            info "Using Java from: $JAVA_HOME"
            break
        fi
    done

    if [[ -z "$JAVA_HOME" ]]; then
        warn "Could not find Java 8, 11, or 17. Using system default which may not work."
        export JAVA_HOME=$(java -XshowSettings:properties -version 2>&1 | grep 'java.home' | awk '{print $3}')
    fi

    export PATH="$JAVA_HOME/bin:$PATH"

    # Set Android SDK
    export ANDROID_HOME="$ANDROID_HOME"
    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"

    # Create local.properties for Jellyfin build (in codebase directory)
    echo "sdk.dir=$ANDROID_HOME" > "$SCRIPT_DIR/codebase/local.properties"
    info "Environment configured."
}

get_emulator_arch() {
    # Detect emulator architecture
    if command -v adb >/dev/null 2>&1 && adb get-state >/dev/null 2>&1; then
        local arch
        arch=$(adb shell getprop ro.product.cpu.abi 2>/dev/null | tr -d '\r\n' || echo "")
        if [[ -n "$arch" ]]; then
            info "Detected emulator architecture: $arch"
            echo "$arch"
            return 0
        fi
    fi

    # Default to universal if can't detect
    warn "Could not detect emulator architecture, building universal APK"
    echo "universal"
}

build_Jellyfin() {
    info "Building Jellyfin from source (this may take several minutes)..."

    local arch
    arch=$(get_emulator_arch)

    ./gradlew clean

    # Build all architectures - Android will create splits automatically
    info "Building Jellyfin (with architecture splits for $arch)"
    ./gradlew assembleJellyfinFreeRelease

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
    APK_SIGNED=$(find build/outputs/apk/JellyfinFree/release/ -name "*-Jellyfin-free-$arch-release.apk" -not -name "*unsigned*" -type f 2>/dev/null | head -1)
    if [[ -n "$APK_SIGNED" ]]; then
        info "APK already signed: $(basename "$APK_SIGNED")"
        return 0
    fi

    # Find unsigned APK to sign (prefer architecture-specific, fallback to universal)
    APK_UNSIGNED=$(find build/outputs/apk/JellyfinFree/release/ -name "*-Jellyfin-free-$arch-release-unsigned.apk" -type f 2>/dev/null | head -1)

    if [[ -z "$APK_UNSIGNED" ]]; then
        warn "No $arch APK found, trying universal APK"
        APK_UNSIGNED=$(find build/outputs/apk/JellyfinFree/release/ -name "*-Jellyfin-free-universal-release-unsigned.apk" -type f 2>/dev/null | head -1)
    fi

    if [[ -z "$APK_UNSIGNED" ]]; then
        fail "No unsigned APK found to sign"
    fi

    info "Signing APK: $APK_UNSIGNED"

    # Use apksigner instead of deprecated jarsigner
    if [[ -z "$ANDROID_HOME" ]]; then
        fail "ANDROID_HOME not set, cannot find apksigner"
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
}


cleanup_update_patch() {
    info "Cleaning up gradle patch..."
    # Revert the patch by applying it in reverse
    if [[ -f "$SCRIPT_DIR/jellyfin-gradle-update.patch" ]]; then
        if patch -R -p0 < "$SCRIPT_DIR/jellyfin-gradle-update.patch"; then
            info "Patch reverted successfully"
        else
            warn "Failed to revert patch - codebase may have modifications"
        fi
    else
        warn "Patch file not found for cleanup"
    fi
}


main() {
    info "Jellyfin Android Setup"
    echo "============================"

    CODEBASE_DIR="$SCRIPT_DIR/codebase"
    if [[ ! -d "$CODEBASE_DIR" ]]; then
        fail "Jellyfin codebase directory not found at $CODEBASE_DIR"
    fi

    cd "$CODEBASE_DIR"

    if [[ ! -f "gradlew" ]]; then
        fail "gradlew not found in codebase directory."
    fi

    apply_update_patch
    check_prerequisites
    setup_environment
    build_Jellyfin
    cleanup_update_patch

    echo ""
    echo "=========================================="
    info "Jellyfin Build complete! Jellyfin is ready to be installed"
    echo "=========================================="
    echo ""
}

main "$@"
