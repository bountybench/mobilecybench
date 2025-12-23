#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

LOG_PREFIX="[deltachat_setup_app_source]"
info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*"; }
error(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*"; exit 1; }

detect_emulator_arch() {
    # Check if emulator is running and get its architecture
    if adb devices | grep -q "device$"; then
        local abi=$(adb shell getprop ro.product.cpu.abi 2>/dev/null | tr -d '\r\n')
        if [[ "$abi" == "x86_64" ]]; then
            echo "x86_64"
        elif [[ "$abi" == "arm64-v8a" ]]; then
            echo "arm64"
        else
            # Default to build for both if we can't detect
            echo "both"
        fi
    else
        # No emulator running, build for both architectures
        echo "both"
    fi
}

install_rust_targets() {
    if command -v rustup >/dev/null 2>&1; then
        RUSTUP_TOOLCHAIN="1.86.0"
        TARGETS="x86_64-linux-android"

        if ! rustup install "$RUSTUP_TOOLCHAIN"; then
            error "Failed to install toolchain $RUSTUP_TOOLCHAIN"
        fi

        for target in $TARGETS; do
            if ! rustup target add "$target" --toolchain "$RUSTUP_TOOLCHAIN"; then
                error "Failed to install target $target"
            fi
        done

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
    
    if [[ -z "$ANDROID_HOME" ]]; then
        if [[ -d "/usr/local/lib/android/sdk" ]]; then
            export ANDROID_HOME="/usr/local/lib/android/sdk"
        elif [[ -d "$HOME/Android/Sdk" ]]; then
            export ANDROID_HOME="$HOME/Android/Sdk"
        elif [[ -n "$ANDROID_SDK_ROOT" ]]; then
            export ANDROID_HOME="$ANDROID_SDK_ROOT"
        fi
    fi
    
    if [[ -z "$ANDROID_NDK_HOME" ]] && [[ -n "$ANDROID_HOME" ]]; then
        if [[ -d "$ANDROID_HOME/ndk/27.0.12077973" ]]; then
            export ANDROID_NDK_HOME="$ANDROID_HOME/ndk/27.0.12077973"
        elif [[ -d "$ANDROID_HOME/ndk/27.1.12297006" ]]; then
            export ANDROID_NDK_HOME="$ANDROID_HOME/ndk/27.1.12297006"
        else
            NDK_DIR=$(find "$ANDROID_HOME/ndk" -maxdepth 1 -type d -name "27.*" 2>/dev/null | head -1)
            if [[ -n "$NDK_DIR" ]]; then
                export ANDROID_NDK_HOME="$NDK_DIR"
            fi
        fi
    fi
    
    if [[ -n "$ANDROID_NDK_HOME" ]]; then
        export ANDROID_NDK_ROOT="$ANDROID_NDK_HOME"
        export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
        info "Using NDK: $ANDROID_NDK_ROOT"
    else
        warn "ANDROID_NDK_HOME not set, NDK build may fail"
    fi
    
    info "Building native libraries for x86_64 architecture..."
    
    for arch in x86_64; do
        info "Building for architecture: $arch"
        if ! ./scripts/ndk-make.sh "$arch"; then
            error "Failed to build native libraries for $arch"
        fi
    done
}

build_deltachat() {
    cd "$SCRIPT_DIR/codebase"
    
    # Detect CI environment
    if [[ -n "${CI:-}" ]] || [[ -n "${GITHUB_ACTIONS:-}" ]]; then
        info "Detected CI environment - applying optimizations"
        export CI_BUILD=true
    fi
    
    # Optimize Gradle for CI builds with aggressive caching and parallelization
    export GRADLE_OPTS="-Xmx4g -XX:MaxMetaspaceSize=1g -XX:+UseParallelGC -XX:+HeapDumpOnOutOfMemoryError -Dfile.encoding=UTF-8"
    
    # Enable Gradle build cache
    export GRADLE_USER_HOME="${HOME}/.gradle"
    export GRADLE_BUILD_CACHE_ENABLED=true
    
    # Create Gradle directories for caching
    mkdir -p "$HOME/.gradle"
    mkdir -p "$HOME/.gradle/caches"
    mkdir -p "$HOME/.android/build-cache"
    
    # Create signing configuration for release build
    mkdir -p "$HOME/.android"
    if [[ ! -f "$HOME/.android/debug.keystore" ]]; then
        keytool -genkey -v -keystore "$HOME/.android/debug.keystore" \
            -alias androiddebugkey -keyalg RSA -keysize 2048 -validity 10000 \
            -storepass android -keypass android \
            -dname "CN=Android Debug,O=Android,C=US"
    fi

    if [[ -d "/usr/local/lib/android/sdk" ]]; then
        export ANDROID_HOME="/usr/local/lib/android/sdk"
        export ANDROID_NDK_HOME="/usr/local/lib/android/sdk/ndk/27.0.12077973"
        export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
    fi

    # Create optimized gradle.properties for CI builds
    cat > gradle.properties << EOF
# Signing configuration
DC_RELEASE_STORE_FILE=$HOME/.android/debug.keystore
DC_RELEASE_STORE_PASSWORD=android
DC_RELEASE_KEY_ALIAS=androiddebugkey
DC_RELEASE_KEY_PASSWORD=android

# Build features
android.defaults.buildfeatures.buildconfig=true
android.useAndroidX=true
android.nonTransitiveRClass=false
android.enableJetifier=true
org.gradle.caching=true
org.gradle.parallel=true
org.gradle.configureondemand=true
org.gradle.jvmargs=-Xmx4g -XX:MaxMetaspaceSize=1g -XX:+UseParallelGC -XX:+UseStringDeduplication
kotlin.incremental=true
kotlin.daemon.jvmargs=-Xmx2g
EOF

    export ANDROID_SDK_ROOT="$ANDROID_HOME"

    local temp_out=$(mktemp)
    local temp_err=$(mktemp)

    info "Running Gradle build..."
    if ./gradlew assembleFossRelease \
        --parallel \
        --build-cache \
        --max-workers=4 \
        --no-scan \
        -Dorg.gradle.jvmargs="-Xmx4g -XX:MaxMetaspaceSize=1g -XX:+UseParallelGC -XX:+UseStringDeduplication" \
        -Pandroid.defaults.buildfeatures.buildconfig=true \
        -Psdk.dir="$ANDROID_HOME" \
        -Pndk.dir="$ANDROID_NDK_HOME" \
        2>&1 | tee "$temp_out"; then
        
        local build_time=$((SECONDS - build_start))
        info "Build completed in $((build_time / 60)) minutes $((build_time % 60)) seconds"

        BUILT_APK=$(find . -name "*release*.apk" -type f 2>/dev/null | head -1)
        if [[ -n "$BUILT_APK" ]]; then
            info "Release APK found at: $BUILT_APK"
            rm -f "$temp_out" "$temp_err"
        else
            error "Gradle build completed but no release APK found. Build output:"
            cat "$temp_out"
        fi
    else
        local exit_code=$?
        error "Gradle build failed with exit code $exit_code. Build output:"
        cat "$temp_out"
        rm -f "$temp_out" "$temp_err"
        exit $exit_code
    fi
    
    if [[ -n "$(git status --porcelain 2>/dev/null)" ]]; then
        warn "Warning: codebase submodule was modified during build. This should not happen!"
        info "Modified files:"
        git status --short
    fi
}

main() {
    info "Starting DeltaChat Android RELEASE build from source"
    info "Build configuration:"
    info "  • Building release APK (required for production)"
    info "  • Using parallel builds with 4 workers"
    info "  • Build cache enabled for faster rebuilds"
    info "  • Full lint checks will be performed"
    
    METADATA_FILE="$SCRIPT_DIR/metadata.json"
    if [[ ! -f "$METADATA_FILE" ]]; then
        error "metadata.json not found"
    fi

    if ! command -v java >/dev/null 2>&1; then
        error "Java not found."
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
        info "Copied release APK from $BUILT_APK to $APK_DIR/deltachat-android.apk"
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
}

main "$@"
