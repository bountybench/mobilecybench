#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

LOG_PREFIX="[deltachat_setup_app_source]"
info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*"; }
error(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*"; exit 1; }

install_rust_targets() {
    if command -v rustup >/dev/null 2>&1; then
        RUSTUP_TOOLCHAIN="1.86.0"
        TARGETS="aarch64-linux-android"

        if ! rustup install "$RUSTUP_TOOLCHAIN"; then
            error "Failed to install toolchain $RUSTUP_TOOLCHAIN"
        fi

        if ! rustup target add $TARGETS --toolchain "$RUSTUP_TOOLCHAIN"; then
            error "Failed to install target $TARGETS"
        fi

        export CARGO_INCREMENTAL=1
        export CARGO_NET_RETRY=10
        export CARGO_HTTP_TIMEOUT=60
        export CARGO_HTTP_LOW_SPEED_LIMIT=10
    else
        error "rustup not found"
    fi
}

build_rust_core() {
    cd "$SCRIPT_DIR/codebase"
    git submodule update --init --recursive
    ./scripts/ndk-make.sh arm64-v8a
}

build_deltachat() {
    cd "$SCRIPT_DIR/codebase"
    export GRADLE_OPTS="$GRADLE_OPTS -Dorg.gradle.caching=true -Dorg.gradle.parallel=true -Dorg.gradle.configureondemand=true"

    # Create signing configuration for release build
    mkdir -p "$HOME/.android"
    if [[ ! -f "$HOME/.android/debug.keystore" ]]; then
        keytool -genkey -v -keystore "$HOME/.android/debug.keystore" \
            -alias androiddebugkey -keyalg RSA -keysize 2048 -validity 10000 \
            -storepass android -keypass android \
            -dname "CN=Android Debug,O=Android,C=US"
    fi

    # Set up Android SDK environment
    if [[ -d "/usr/local/lib/android/sdk" ]]; then
        export ANDROID_HOME="/usr/local/lib/android/sdk"
        export ANDROID_NDK_HOME="/usr/local/lib/android/sdk/ndk/27.0.12077973"
        export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
    fi

    # Create gradle.properties with signing configuration and build features
    cat > gradle.properties << EOF
DC_RELEASE_STORE_FILE=$HOME/.android/debug.keystore
DC_RELEASE_STORE_PASSWORD=android
DC_RELEASE_KEY_ALIAS=androiddebugkey
DC_RELEASE_KEY_PASSWORD=android
android.defaults.buildfeatures.buildconfig=true
EOF

    # Also create local.properties for Android SDK paths
    cat > local.properties << EOF
sdk.dir=$ANDROID_HOME
ndk.dir=$ANDROID_NDK_HOME
EOF

    local temp_out=$(mktemp)
    local temp_err=$(mktemp)

    # Run Gradle build and check if APK was actually created
    info "Running Gradle build..."
    if ./gradlew assembleFossRelease \
        --daemon \
        --parallel \
        --build-cache \
        --configure-on-demand \
        --max-workers=4 \
        --info \
        -Dorg.gradle.jvmargs="-Xmx4g -XX:MaxMetaspaceSize=1g -XX:+UseParallelGC -XX:+UseStringDeduplication" \
        -Pandroid.defaults.buildfeatures.buildconfig=true \
        2>&1 | tee "$temp_out"; then

        # Check if APK was actually built in the expected location
        BUILT_APK=$(find . -name "*release*.apk" -type f 2>/dev/null | head -1)
        if [[ -n "$BUILT_APK" ]]; then
            info "APK found at: $BUILT_APK"
            rm -f "$temp_out" "$temp_err"
        else
            error "Gradle build completed but no APK found. Build output:"
            cat "$temp_out"
        fi
    else
        local exit_code=$?
        error "Gradle build failed with exit code $exit_code. Build output:"
        cat "$temp_out"
        rm -f "$temp_out" "$temp_err"
        exit $exit_code
    fi
}

main() {
    METADATA_FILE="$SCRIPT_DIR/metadata.json"
    if [[ ! -f "$METADATA_FILE" ]]; then
        error "metadata.json not found"
    fi

    if ! command -v java >/dev/null 2>&1; then
        error "Java not found"
    fi

    if ! command -v "$SCRIPT_DIR/codebase/gradlew" >/dev/null 2>&1; then
        error "Gradle wrapper not found"
    fi

    install_rust_targets
    
    build_rust_core
    build_deltachat

    APK_DIR="$SCRIPT_DIR/apk"
    mkdir -p "$APK_DIR"

    BUILT_APK=$(find . -name "*release*.apk" -type f | head -1)
    if [[ -n "$BUILT_APK" ]]; then
        cp "$BUILT_APK" "$APK_DIR/deltachat-android.apk"
        info "Copied APK from $BUILT_APK to $APK_DIR/deltachat-android.apk"
    else
        error "No release APK found in build output"
    fi

    APK_FILE="$APK_DIR/deltachat-android.apk"
    if [[ ! -f "$APK_FILE" ]]; then
        error "APK file not found"
    fi

    FILE_SIZE=$(stat -c%s "$APK_FILE" 2>/dev/null || stat -f%z "$APK_FILE" 2>/dev/null || echo "0")
    if [[ "$FILE_SIZE" -lt 1048576 ]]; then
        error "APK too small ($FILE_SIZE bytes)"
    fi

    if [[ -f "$SCRIPT_DIR/setup_app_apklink.sh" ]]; then
        "$SCRIPT_DIR/setup_app_apklink.sh"
    else
        warn "setup_app_apklink.sh not found"
    fi
}

main "$@"
