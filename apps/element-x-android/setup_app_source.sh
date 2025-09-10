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
        "-x" "lint"
        "-x" "lintDebug"
        "-x" "detekt"
        "-x" "ktlintCheck"
        "-x" "test"
        "-x" "testDebugUnitTest"
    )
    
    # Try only fastest variant first with 12 minute timeout
    if command -v gtimeout >/dev/null 2>&1; then
        TIMEOUT_CMD="gtimeout 720"
    elif command -v timeout >/dev/null 2>&1; then
        TIMEOUT_CMD="timeout 720"
    else
        TIMEOUT_CMD=""
    fi
    
    if $TIMEOUT_CMD ./gradlew assembleDebug "${BUILD_ARGS[@]}"; then
        info "✅ Build completed: assembleDebug"
        return 0
    fi
    
    warn "Standard build failed, trying FDroid variant..."
    if $TIMEOUT_CMD ./gradlew assembleFdroidDebug "${BUILD_ARGS[@]}"; then
        info "✅ Build completed: assembleFdroidDebug"
        return 0
    fi
    
    error "All build variants failed within time limit"
}

find_apk() {
    # Find any debug APK in build outputs
    APK_PATH=$(find app/build/outputs/apk -name "*debug*.apk" -type f 2>/dev/null | head -1)
    [[ -n "$APK_PATH" ]] || error "No APK found after build"
    
    info "✅ APK: $APK_PATH"
    export APK_PATH
}

main() {
    info "Building Element X Android APK"
    
    CODEBASE_DIR="$SCRIPT_DIR/codebase"
    [[ -d "$CODEBASE_DIR" && -f "$CODEBASE_DIR/gradlew" ]] || error "Element X codebase not found at $CODEBASE_DIR"
    
    cd "$CODEBASE_DIR"
    check_prerequisites
    setup_environment
    build_apk
    find_apk
    
    info "✅ Build completed successfully!"
    info "APK: $APK_PATH"
}

main "$@"