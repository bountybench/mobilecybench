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

    # More robust check for the Android SDK path
    if [ -n "$ANDROID_HOME" ] && [ -d "$ANDROID_HOME" ]; then
        info "Using Android SDK from pre-set ANDROID_HOME: $ANDROID_HOME"
    elif [ -d "${HOME}/.android-sdk" ]; then
        # Fallback to the default path if ANDROID_HOME isn't set
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
    info "Setting up optimized build environment..."
    
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
    
    # Performance optimizations - aggressive memory and CPU settings
    export GRADLE_OPTS="-Xmx8g -XX:+UseG1GC -XX:+UseStringDeduplication -XX:MaxGCPauseMillis=100 -XX:+UseCompressedOops"
    export JAVA_TOOL_OPTIONS="-XX:+TieredCompilation -XX:TieredStopAtLevel=1"
    
    # Increase file descriptor limit for faster I/O
    ulimit -n 65536 2>/dev/null || ulimit -n 10240 2>/dev/null || true
    
    # Create local.properties for Element X build
    echo "sdk.dir=$ANDROID_HOME" > "$SCRIPT_DIR/codebase/local.properties"
    
    info "Environment configured with performance optimizations."
}

get_emulator_arch() {
    # Detect emulator architecture early for native library optimization
    local detected_arch=""
    
    if command -v adb >/dev/null 2>&1 && adb get-state >/dev/null 2>&1; then
        detected_arch=$(adb shell getprop ro.product.cpu.abi 2>/dev/null | tr -d '\r\n' || echo "")
    fi
    
    # Fallback to host architecture if no device connected
    if [[ -z "$detected_arch" ]]; then
        local host_arch=$(uname -m)
        case "$host_arch" in
            "arm64"|"aarch64") detected_arch="arm64-v8a" ;;
            "x86_64"|"amd64") detected_arch="x86_64" ;;
            "i386"|"i686") detected_arch="x86" ;;
            *) detected_arch="arm64-v8a" ;;
        esac
        info "No device connected, using host architecture: $detected_arch"
    else
        info "Detected device architecture: $detected_arch"
    fi
    
    echo "$detected_arch"
}

clean_build_artifacts() {
    # Remove only unnecessary build artifacts to save storage
    info "Cleaning build artifacts to save storage..."
    
    # Stop any running Gradle daemons
    ./gradlew --stop >/dev/null 2>&1 || true
    
    # Clean up old APKs except fdroid debug
    find . -path "*/build/outputs/apk" -name "*.apk" -not -path "*/fdroid/debug/*" -delete 2>/dev/null || true
    
    # Clean up intermediate files that consume storage
    find . -path "*/build/intermediates/dex*" -type d -exec rm -rf {} + 2>/dev/null || true
    find . -path "*/build/intermediates/transforms" -type d -exec rm -rf {} + 2>/dev/null || true
    find . -path "*/build/tmp" -type d -exec rm -rf {} + 2>/dev/null || true
    find . -path "*/build/kotlin/sessions" -type d -exec rm -rf {} + 2>/dev/null || true
    
    # Clean up test build outputs
    find . -path "*/build/outputs/apk/*/test/*" -delete 2>/dev/null || true
    find . -path "*/build/intermediates/*/test*" -type d -exec rm -rf {} + 2>/dev/null || true
    
    # Clean up gradle cache to save memory - more aggressive cleanup
    rm -rf ~/.gradle/caches/transforms-* 2>/dev/null || true
    rm -rf ~/.gradle/caches/*/kotlin-dsl 2>/dev/null || true
    rm -rf ~/.gradle/caches/*/scripts 2>/dev/null || true
    rm -rf ~/.gradle/caches/*/executionHistory 2>/dev/null || true
    
    # Clean up local build cache files over 100MB
    find . -path "*/build/*" -type f -size +100M -delete 2>/dev/null || true
}

build_element_x() {
    local arch
    arch=$(get_emulator_arch)
    
    # Check if APK already exists and is recent
    APK_PATH="app/build/outputs/apk/fdroid/debug/app-fdroid-debug.apk"
    if [[ -f "$APK_PATH" ]]; then
        # Check if APK is newer than source changes
        local last_commit_time=$(git log -1 --format="%ct" 2>/dev/null || echo "0")
        local apk_time=$(stat -f "%m" "$APK_PATH" 2>/dev/null || stat -c "%Y" "$APK_PATH" 2>/dev/null || echo "0")
        
        if [[ "$apk_time" -gt "$last_commit_time" ]]; then
            info "APK already exists and is up-to-date at $APK_PATH - skipping build"
            return 0
        else
            info "APK exists but source has changed - rebuilding"
        fi
    fi
    
    # Clean before build
    clean_build_artifacts
    
    info "Building Element X from source (optimized for $arch architecture)..."
    
    # Build with Gradle 9.0 compatible optimizations (removed deprecated features)
    ./gradlew assembleFdroidDebug \
        --no-daemon \
        --stacktrace \
        --console=plain \
        --parallel \
        --build-cache \
        --configuration-cache \
        --warning-mode=all \
        --max-workers=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo "4") \
        -Dorg.gradle.jvmargs="-Xmx8g -XX:+UseG1GC -XX:MaxMetaspaceSize=2g -XX:+DisableExplicitGC -XX:+UseStringDeduplication -XX:+UseCompressedOops" \
        -Dorg.gradle.parallel=true \
        -Dorg.gradle.caching=true \
        -Dkotlin.incremental=true \
        -Pandroid.injected.build.abi="$arch" \
        -x test \
        -x testClasses \
        -x connectedCheck \
        -x deviceCheck \
        -x detekt \
        -x ktlintCheck \
        -x ktlintFormat \
        -x compileGplayReleaseKotlin \
        -x compileFdroidReleaseKotlin \
        -x compileReleaseKotlin \
        -x assembleGplayDebug \
        -x assembleGplayRelease \
        -x assembleFdroidRelease \
        -x assembleRelease \
        -x bundleDebug \
        -x bundleRelease \
        -x bundleGplayDebug \
        -x bundleGplayRelease \
        -x bundleFdroidRelease
    
    # Post-build cleanup to save storage
    clean_build_artifacts
    
    info "Build completed successfully with storage optimization."
}

main() {
    info "Element X Android Setup"
    echo "========================"
    
    CODEBASE_DIR="$SCRIPT_DIR/codebase"
    if [[ ! -d "$CODEBASE_DIR" ]]; then
        error "Element X codebase directory not found at $CODEBASE_DIR"
    fi
    
    cd "$CODEBASE_DIR"
    
    if [[ ! -f "gradlew" ]]; then
        error "gradlew not found in codebase directory."
    fi
    
    check_prerequisites
    setup_environment
    build_element_x
    
    echo ""
    echo "=========================================="
    info "Element X APK build completed successfully!"
    echo "=========================================="
    echo ""
}

main "$@"