#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

LOG_PREFIX="[setup_app_source]"
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
    
    # Create local.properties for Element X build (in codebase directory)
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
            # Map to Gradle ABI format
            case "$arch" in
                "arm64-v8a") echo "arm64-v8a" ;;
                "armeabi-v7a") echo "armeabi-v7a" ;;
                "x86_64") echo "x86_64" ;;
                "x86") echo "x86" ;;
                *) echo "arm64-v8a" ;;
            esac
            return 0
        fi
    fi
    
    # Default to arm64-v8a if can't detect
    warn "Could not detect emulator architecture, defaulting to arm64-v8a"
    echo "arm64-v8a"
}

build_element_x() {
    info "Building Element X from source (optimized for speed)..."

    local arch
    arch=$(get_emulator_arch)
    
    # Speed optimizations - skip clean, use cache
    info "Building Element X FDroid debug variant for $arch architecture"
    
    # Ultra-fast build with aggressive optimizations and forced architecture
    info "Forcing build for $arch architecture only"
    ./gradlew assembleFdroidDebug \
        --no-daemon \
        --stacktrace \
        --console=plain \
        --parallel \
        --build-cache \
        --configuration-cache \
        -Dorg.gradle.jvmargs="-Xmx4g -XX:+UseParallelGC -XX:MaxMetaspaceSize=1g" \
        -Pkotlin.incremental=true \
        -Pkotlin.compiler.execution.strategy=in-process \
        -Pandroid.injected.build.abi="$arch" \
        -PabiFilters="$arch" \
        -x test \
        -x lint \
        -x detekt \
        -x ktlintCheck \
        -x testDebugUnitTest \
        -x lintDebug \
        -x compileDebugUnitTestSources \
        -x generateDebugUnitTestSources \
        -x processDebugUnitTestManifest
    
    info "Build completed successfully."
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