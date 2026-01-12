#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODEBASE_DIR="${SCRIPT_DIR}/codebase"

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
        error "Java not found. Please install Java 21."
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
    
    export PATH="$JAVA_HOME/bin:$PATH"
    
    # Set Android SDK
    export ANDROID_HOME="$ANDROID_HOME"
    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
    
    # Create local.properties for build (in codebase directory)
    echo "sdk.dir=$ANDROID_HOME" > "$CODEBASE_DIR/local.properties"
    info "Environment configured."
}

generate_keystore() {
    info "Checking/Generating debug keystore..."
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
    else
        info "Using existing debug keystore at $KEYSTORE_FILE"
    fi
}

build_app() {
    info "Building FairEmail from source (this may take several minutes)..."
    cd "$CODEBASE_DIR"

    generate_keystore
    KEYSTORE_FILE="$HOME/.android/debug.keystore"

    # Create keystore.properties so the release build can sign with our debug key
    echo "storeFile=$KEYSTORE_FILE" > keystore.properties
    echo "storePassword=android" >> keystore.properties
    echo "keyAlias=androiddebugkey" >> keystore.properties
    echo "keyPassword=android" >> keystore.properties

    # Run gradle build
    chmod +x gradlew
    ./gradlew clean
    ./gradlew assembleGithubRelease
    
    info "Build completed successfully."
    sign_apk
}

sign_apk() {
    info "Finalizing APK..."
    cd "$CODEBASE_DIR"
    
    # We essentially already signed it during build with the debug keystore masquerading as release key.
    # But let's find the output and move it.

    KEYSTORE_FILE="$HOME/.android/debug.keystore"
    start_dir=$(pwd)
    
    # Check for signed APK first (since we provided keystore)
    APK_SIGNED_FOUND=$(find app/build/outputs/apk/github/release/ -name "*-github-release.apk" -type f 2>/dev/null | head -1)
    
    if [[ -z "$APK_SIGNED_FOUND" ]]; then
       # Fallback to unsigned check (if our signing config failed silently but build passed)
       warn "No signed release APK found. Checking for unsigned..."
       APK_UNSIGNED=$(find app/build/outputs/apk/github/release/ -name "*-github-release-unsigned.apk" -type f 2>/dev/null | head -1)
       
       if [[ -z "$APK_UNSIGNED" ]]; then
           error "Could not find any release APK."
       fi
       
       # ... logic to sign if needed ...
       # Since we provided properties, we expect it to be signed.
       # But if we must manual sign:
       cp "$APK_UNSIGNED" "temp_unsigned.apk"
       
        # Find latest build tools
        BUILD_TOOL_DIR=$(ls -d "$ANDROID_HOME/build-tools/"* | sort -V | tail -n1)
        APKSIGNER="$BUILD_TOOL_DIR/apksigner"
        
        APK_DEST="${SCRIPT_DIR}/apk/fairemail.apk"
        mkdir -p "${SCRIPT_DIR}/apk"

        if [[ -f "$APKSIGNER" ]]; then
            info "Using apksigner from $APKSIGNER"
            "$APKSIGNER" sign --ks "$KEYSTORE_FILE" --ks-key-alias androiddebugkey --ks-pass pass:android --key-pass pass:android --out "$APK_DEST" "temp_unsigned.apk"
        else
            warn "apksigner not found. Falling back to jarsigner."
            cp "temp_unsigned.apk" "$APK_DEST"
            jarsigner -verbose -sigalg SHA1withRSA -digestalg SHA1 -keystore "$KEYSTORE_FILE" -storepass android "$APK_DEST" androiddebugkey
        fi
        rm "temp_unsigned.apk"
    else
        # Just copy the signed one
        info "Found signed APK: $APK_SIGNED_FOUND"
        mkdir -p "${SCRIPT_DIR}/apk"
        cp "$APK_SIGNED_FOUND" "${SCRIPT_DIR}/apk/fairemail.apk"
    fi
    
    info "FairEmail APK ready at ${SCRIPT_DIR}/apk/fairemail.apk"
}

check_prerequisites
setup_environment
build_app
