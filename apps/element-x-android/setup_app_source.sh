#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANDROID_HOME="${ANDROID_HOME:-${HOME}/.android-sdk}"

LOG_PREFIX="[setup_app_source]"
info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*"; }
error(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*"; exit 1; }

check_prerequisites() {
    info "Checking prerequisites..."
    
    # Check Java
    command -v java >/dev/null 2>&1 || error "Java not found. Please install Java 17."
    
    # Check Android SDK
    if [[ ! -d "$ANDROID_HOME" ]]; then
        # Try common locations
        for location in "${HOME}/.android-sdk" "/usr/local/lib/android/sdk"; do
            if [[ -d "$location" ]]; then
                ANDROID_HOME="$location"
                break
            fi
        done
        [[ -d "$ANDROID_HOME" ]] || error "Android SDK not found. Please set ANDROID_HOME."
    fi
    
    info "Using Android SDK: $ANDROID_HOME"
}

setup_environment() {
    # Set JAVA_HOME if not set
    if [[ -z "$JAVA_HOME" ]]; then
        if command -v /usr/libexec/java_home >/dev/null 2>&1; then
            export JAVA_HOME="$(/usr/libexec/java_home 2>/dev/null)"
        fi
    fi
    
    export ANDROID_HOME PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
    
    # Optimize Gradle for faster builds
    export GRADLE_OPTS="-Xmx8g -XX:+UseG1GC -XX:MaxMetaspaceSize=1g -Dfile.encoding=UTF-8"
}

build_apk() {
    info "Building Element X APK (optimized for speed)..."
    
    # Aggressive build optimizations to prevent timeout
    BUILD_ARGS=(
        "--no-daemon"
        "--stacktrace" 
        "--console=plain"
        "--parallel"
        "--build-cache"
        "--configuration-cache"
        "--max-workers=4"
        "-Porg.gradle.jvmargs=-Xmx8g"
        "-Pkotlin.incremental=true"
        "-Pandroid.injected.build.abi=arm64-v8a"
        "-x" "lint"
        "-x" "lintDebug"
        "-x" "detekt"
        "-x" "ktlintCheck"
        "-x" "test"
        "-x" "testDebugUnitTest"
    )
    
    # Build only FDroid debug variant (fastest single variant)
    if command -v gtimeout >/dev/null 2>&1; then
        TIMEOUT_CMD="gtimeout 1200"
    elif command -v timeout >/dev/null 2>&1; then
        TIMEOUT_CMD="timeout 1200"
    else
        TIMEOUT_CMD=""
    fi
    
    info "Building FDroid debug variant only (fastest option)..."
    if $TIMEOUT_CMD ./gradlew assembleFdroidDebug "${BUILD_ARGS[@]}"; then
        info "✅ Build completed: assembleFdroidDebug"
        return 0
    fi
    
    error "FDroid debug build failed within time limit"
}


main() {
    info "Building Element X Android APK"
    
    CODEBASE_DIR="$SCRIPT_DIR/codebase"
    [[ -d "$CODEBASE_DIR" && -f "$CODEBASE_DIR/gradlew" ]] || error "Element X codebase not found at $CODEBASE_DIR"
    
    cd "$CODEBASE_DIR"
    check_prerequisites
    setup_environment
    build_apk
    
    info "✅ Build completed successfully!"
}

main "$@"