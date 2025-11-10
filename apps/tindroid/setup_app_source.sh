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

# Cross-platform sed in-place function
sed_inplace() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "$@"
    else
        sed -i "$@"
    fi
}

check_prerequisites() {
    info "Checking prerequisites (Java and Android SDK)..."
    
    # Check Java
    if ! command -v java >/dev/null 2>&1; then
        error "Java not found. Please install Java 17."
    fi

    # More robust check for the Android SDK path.
    if [ -n "$ANDROID_HOME" ] && [ -d "$ANDROID_HOME" ]; then
      info "Using Android SDK from pre-set ANDROID_HOME: $ANDROID_HOME"
    elif [ -d "/usr/local/lib/android/sdk" ]; then
      # GitHub Actions default path
      ANDROID_HOME="/usr/local/lib/android/sdk"
      info "Found Android SDK at GitHub Actions location: $ANDROID_HOME"
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
    
    # Create local.properties for Tindroid build (in codebase directory)
    CODEBASE_DIR="$SCRIPT_DIR/codebase"
    echo "sdk.dir=$ANDROID_HOME" > "$CODEBASE_DIR/local.properties"

    # Create keystore.properties and debug.keystore
    echo "storeFile=debug.keystore
storePassword=android
keyAlias=androiddebugkey
keyPassword=android" > "$CODEBASE_DIR/keystore.properties"
    KEYSTORE_FILE="$CODEBASE_DIR/app/debug.keystore"
    if [ ! -f "$KEYSTORE_FILE" ]; then
        info "Creating debug keystore for Tindroid build..."
        keytool -genkey -v -keystore "$KEYSTORE_FILE" \
                -alias androiddebugkey -keyalg RSA -keysize 2048 \
                -validity 10000 -storepass android -keypass android \
                -dname "CN=Android Debug, O=Android, C=US"
        info "Debug keystore created at $KEYSTORE_FILE"
    fi

    # There should be a dummy google-services.json file in the Tindroid root directory.
    # The Tindroid app requires Firebase services for all build variants.
    # Copy google-services.json from the Tindroid root directory to app/google-services.json inside the codebase directory.
    if [ ! -f "$SCRIPT_DIR/google-services.json" ]; then
        error "google-services.json not found in the Tindroid root directory. Please copy a valid google-services.json file to the Tindroid root directory."
    else
        cp "$SCRIPT_DIR/google-services.json" "$CODEBASE_DIR/app/google-services.json"
    fi
    
    info "Environment configured."
}

patch_gradle_properties() {
    info "Patching gradle.properties for Java 17 compatibility..."
    
    GRADLE_PROPERTIES="$CODEBASE_DIR/gradle.properties"
    if [[ ! -f "$GRADLE_PROPERTIES" ]]; then
        warn "gradle.properties not found at $GRADLE_PROPERTIES, skipping patch"
        return
    fi
    
    # Remove -XX:MaxPermSize option (not supported in Java 8+)
    if grep -q "MaxPermSize" "$GRADLE_PROPERTIES"; then
        info "Removing incompatible -XX:MaxPermSize option from gradle.properties"
        # Remove MaxPermSize option from org.gradle.jvmargs line
        sed_inplace 's/-XX:MaxPermSize=[0-9]*[kmgKMG]//g' "$GRADLE_PROPERTIES"
        # Clean up any double spaces that might result
        sed_inplace 's/  / /g' "$GRADLE_PROPERTIES"
        info "gradle.properties patched successfully"
    else
        info "gradle.properties already compatible (no MaxPermSize found)"
    fi
}

build_tindroid() {
    info "Building Tindroid from source (this may take several minutes)..."

    # Check if APK already exists
    EXISTING_APK=$(find app/build/outputs/apk/release -name "*.apk" -type f 2>/dev/null | head -n1)
    if [[ -n "$EXISTING_APK" ]]; then
        info "APK already exists at $EXISTING_APK - skipping build"
    else
        # Clean everything and rebuild
        info "Cleaning build cache and rebuilding..."
        ./gradlew --stop
        ./gradlew clean

        # Build universal release APK (signed by build.gradle's signingConfig)
        info "Building Tindroid (universal APK)"
        ./gradlew assembleRelease

        info "Build completed successfully."
    fi

    # Find and copy APK to standard location
    APK_PATH=$(find app/build/outputs/apk/release -name "*.apk" -type f 2>/dev/null | head -n1)
    if [[ -z "$APK_PATH" ]]; then
        error "No APK found in app/build/outputs/apk/release"
    fi

    mkdir -p "$SCRIPT_DIR/apk"
    cp -f "$APK_PATH" "$SCRIPT_DIR/apk/tindroid.apk"
    info "APK copied to: $SCRIPT_DIR/apk/tindroid.apk"
}

main() {
    info "Tindroid Android Setup"
    echo "====================="
    
    CODEBASE_DIR="$SCRIPT_DIR/codebase"
    if [[ ! -d "$CODEBASE_DIR" ]]; then
        error "Tindroid codebase directory not found at $CODEBASE_DIR"
    fi
    
    cd "$CODEBASE_DIR"
    
    if [[ ! -f "gradlew" ]]; then
        error "gradlew not found in codebase directory."
    fi
    
    check_prerequisites
    setup_environment
    patch_gradle_properties
    build_tindroid
    
    echo ""
    echo "=========================================="
    info "Tindroid Build complete! Tindroid is ready to be installed"
    echo "=========================================="
    echo ""
}

# Run main function
main "$@"
