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
        
        local arch=$(detect_emulator_arch)
        local targets=""
        
        case "$arch" in
            "x86_64")
                targets="x86_64-linux-android"
                info "Building for x86_64 (detected running emulator)"
                ;;
            "arm64")
                targets="aarch64-linux-android"
                info "Building for arm64 (detected running emulator)"
                ;;
            *)
                targets="aarch64-linux-android x86_64-linux-android"
                info "Building for both architectures (no emulator detected or unknown arch)"
                ;;
        esac

        if ! rustup install "$RUSTUP_TOOLCHAIN"; then
            error "Failed to install toolchain $RUSTUP_TOOLCHAIN"
        fi

        for target in $targets; do
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
    
    local arch=$(detect_emulator_arch)
    local ndk_targets=""
    
    case "$arch" in
        "x86_64")
            ndk_targets="x86_64"
            info "Building Rust core for x86_64"
            ;;
        "arm64")
            ndk_targets="arm64-v8a"
            info "Building Rust core for arm64-v8a"
            ;;
        *)
            ndk_targets="arm64-v8a x86_64"
            info "Building Rust core for both architectures"
            ;;
    esac
    
    for target in $ndk_targets; do
        info "Building Rust core for $target..."
        ./scripts/ndk-make.sh "$target"
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
    
    # Create Gradle directory
    mkdir -p "$HOME/.gradle"
    mkdir -p "$HOME/.gradle/caches"
    
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
android.enableJetifier=true

# Performance optimizations for CI
org.gradle.daemon=true
org.gradle.parallel=true
org.gradle.configureondemand=true
org.gradle.caching=true

# Memory settings
org.gradle.jvmargs=-Xmx4g -XX:MaxMetaspaceSize=1g -XX:+UseParallelGC -XX:+HeapDumpOnOutOfMemoryError
EOF

    export ANDROID_SDK_ROOT="$ANDROID_HOME"

    mkdir -p src/main/res/values
    if ! grep -q "zxing_msg_camera_framework_bug" src/main/res/values/strings.xml 2>/dev/null; then
        sed -i '/<\/resources>/i\    <string name="zxing_msg_camera_framework_bug">Camera framework bug detected</string>' src/main/res/values/strings.xml 2>/dev/null || echo '<resources><string name="zxing_msg_camera_framework_bug">Camera framework bug detected</string></resources>' > src/main/res/values/missing_strings.xml
    fi
    if ! grep -q "toolbarStyle" src/main/res/values/attrs.xml 2>/dev/null; then
        sed -i '/<\/resources>/i\    <attr name="toolbarStyle" format="reference" />' src/main/res/values/attrs.xml 2>/dev/null || echo '<resources><attr name="toolbarStyle" format="reference" /></resources>' > src/main/res/values/missing_attrs.xml
    fi
    mkdir -p src/main/res/values
    cat > src/main/res/values/missing_ids.xml << EOF
<?xml version="1.0" encoding="utf-8"?>
<resources>
    <item name="search_close_btn" type="id" />
</resources>
EOF

    local temp_out=$(mktemp)
    local temp_err=$(mktemp)

    # Create Gradle cache directory
    mkdir -p "$HOME/.gradle/caches"
    
    # Clean up any previous interrupted builds
    info "Cleaning any previous interrupted builds..."
    ./gradlew --stop 2>/dev/null || true
    rm -rf build/intermediates 2>/dev/null || true
    
    # Run Gradle build
    info "Running Gradle build for release APK..."
    
    # Start timer
    local build_start=$SECONDS
    
    # Always use release build - this is required for production
    local build_task="assembleFossRelease"
    info "Building RELEASE APK (required for production use)"
    
    if ./gradlew "$build_task" \
        --daemon \
        --parallel \
        --build-cache \
        --max-workers=4 \
        --console=plain \
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
