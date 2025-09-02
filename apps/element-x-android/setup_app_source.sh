#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANDROID_HOME="${HOME}/.android-sdk"

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
        ANDROID_HOME="${HOME}/.android-sdk"
        info "Found Android SDK at default location: $ANDROID_HOME"
    elif [ -d "/usr/local/lib/android/sdk" ]; then
        ANDROID_HOME="/usr/local/lib/android/sdk"
        info "Found Android SDK at: $ANDROID_HOME"
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
    elif command -v /usr/libexec/java_home &>/dev/null; then
        export JAVA_HOME="$(/usr/libexec/java_home -v 17 2>/dev/null || /usr/libexec/java_home)"
    else
        warn "Could not find Java 17 via known paths. Using system default."
        export JAVA_HOME=$(java -XshowSettings:properties -version 2>&1 | grep 'java.home' | awk '{print $3}' | head -1)
    fi
    
    export PATH="$JAVA_HOME/bin:$PATH"
    
    # Set Android SDK
    export ANDROID_HOME="$ANDROID_HOME"
    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
    
    info "Environment configured."
    info "Java Home: $JAVA_HOME"  
    info "Android Home: $ANDROID_HOME"
}

build_element_x() {
    info "Building Element X from source (this may take several minutes)..."

    # Disable caching which seems to be causing issues
    info "Disabling Gradle caching to avoid file system issues..."
    
    # Build with caching disabled and other conservative settings
    if ./gradlew assembleDebug --no-daemon --no-build-cache --no-parallel --stacktrace --warning-mode=none \
       -Dorg.gradle.jvmargs="-Xmx2g -XX:MaxMetaspaceSize=512m" \
       -Dkotlin.daemon.jvmargs="-Xmx1g"; then
        info "✅ Build completed successfully!"
        return 0
    else
        warn "Standard build failed, trying FDroid variant without caching..."
        
        # Try FDroid variant with caching completely disabled
        if ./gradlew assembleFdroidDebug --no-daemon --no-build-cache --no-parallel --stacktrace --warning-mode=none \
           -Dorg.gradle.caching=false; then
            info "✅ FDroid debug build completed successfully!"
            return 0
        else
            # Final attempt: just try basic build without complex flags
            warn "Trying basic build approach..."
            if ./gradlew assembleFdroidDebug --no-daemon; then
                info "✅ Basic build completed successfully!"
                return 0
            else
                error "Build failed after all attempts. Check error details above."
                return 1
            fi
        fi
    fi
}

find_apk() {
    info "Locating generated APK..."
    
    # Look for the generated debug APK - try multiple patterns
    APK_PATH=$(find app/build/outputs/apk -name "*debug*.apk" -type f 2>/dev/null | head -1)
    
    # If not found, try looking for FDroid debug specifically
    if [[ -z "$APK_PATH" ]]; then
        APK_PATH=$(find app/build/outputs/apk -name "*fdroid*debug*.apk" -type f 2>/dev/null | head -1)
    fi
    
    # If still not found, try any APK
    if [[ -z "$APK_PATH" ]]; then
        APK_PATH=$(find app/build/outputs -name "*.apk" -type f 2>/dev/null | head -1)
    fi
    
    if [[ -z "$APK_PATH" ]]; then
        warn "No APK found. Listing build outputs:"
        find app/build -name "*.apk" -type f 2>/dev/null | head -10 || echo "No APKs found in build directory"
        return 1
    fi
    
    info "✅ Found APK: $APK_PATH"
    export APK_PATH
    return 0
}

main() {
    info "Element X Android Setup"
    echo "========================"
    
    # Navigate to codebase directory
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
    
    if build_element_x; then
        if find_apk; then
            echo ""
            echo "=========================================="
            info "✅ Element X build completed successfully!"
            info "APK location: $APK_PATH"
            info "Element X is ready for testing."
            echo "=========================================="
        else
            warn "Build completed but APK not found"
        fi
    else
        error "Build failed"
    fi
}

main "$@"