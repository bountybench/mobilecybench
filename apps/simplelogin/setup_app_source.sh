#!/bin/bash

# SimpleLogin Android App Source Setup Script
# Part of MobileCybench - builds and installs SimpleLogin Android app

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODEBASE_DIR="$SCRIPT_DIR/codebase"
METADATA_FILE="$SCRIPT_DIR/metadata.json"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_prerequisites() {
    log_info "Checking prerequisites..."
    
    # Check if metadata exists
    if [[ ! -f "$METADATA_FILE" ]]; then
        log_error "metadata.json not found at $METADATA_FILE"
        return 1
    fi
    
    # Check Java
    if ! command -v java &> /dev/null; then
        log_error "Java not found. Please install Java 17 or later."
        return 1
    fi
    
    # Set Android SDK path - handle both local development and CI environments
    if [[ -n "$ANDROID_HOME" && -d "$ANDROID_HOME" ]]; then
        # Use existing ANDROID_HOME if set and valid
        log_info "Using existing ANDROID_HOME: $ANDROID_HOME"
    elif [[ -d "/usr/local/lib/android/sdk" ]]; then
        # GitHub Actions default path
        ANDROID_HOME="/usr/local/lib/android/sdk"
        log_info "Using GitHub Actions Android SDK path: $ANDROID_HOME"
    elif [[ -d "${HOME}/.android-sdk" ]]; then
        # Local development default path
        ANDROID_HOME="${HOME}/.android-sdk"
        log_info "Using local development Android SDK path: $ANDROID_HOME"
    else
        log_error "Android SDK not found in any expected location"
        return 1
    fi
    
    # Check Android SDK
    if [[ ! -d "$ANDROID_HOME" ]]; then
        log_error "Android SDK not found at $ANDROID_HOME. Please run the Android emulator setup first."
        return 1
    fi
    
    # Set up Android SDK environment
    export ANDROID_HOME="$ANDROID_HOME"
    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
    
    # Check ADB
    if ! command -v adb &> /dev/null; then
        log_error "adb not found. Please install Android SDK platform-tools."
        return 1
    fi
    
    # Check Git
    if ! command -v git &> /dev/null; then
        log_error "git not found. Please install git."
        return 1
    fi
    
    log_success "Prerequisites check passed"
}


configure_debug_build() {
    log_info "Configuring debug build with local API endpoint..."
    
    # Ensure codebase directory exists (for submodule approach)
    if [[ ! -d "$CODEBASE_DIR" ]]; then
        log_error "Codebase directory not found at $CODEBASE_DIR"
        log_info "This may indicate a submodule initialization issue"
        return 1
    fi
    
    cd "$CODEBASE_DIR"
    
    # Create debug build variant configuration
    # SimpleLogin project structure: SimpleLogin/app/ is the main module
    local debug_config_dir="SimpleLogin/app/src/debug"
    mkdir -p "$debug_config_dir/res/xml"
    
    # Create network security config for debug builds
    cat > "$debug_config_dir/res/xml/network_security_config.xml" << 'EOF'
<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
    <domain-config cleartextTrafficPermitted="true">
        <domain includeSubdomains="true">10.0.2.2</domain>
        <domain includeSubdomains="true">localhost</domain>
        <domain includeSubdomains="true">127.0.0.1</domain>
    </domain-config>
</network-security-config>
EOF
    
    # Look for API endpoint configuration files and update them
    # These are common locations where API endpoints might be configured
    local config_files=(
        "SimpleLogin/app/src/main/java/io/simplelogin/android/utils/Constants.kt"
        "SimpleLogin/app/src/main/java/io/simplelogin/android/utils/Constants.java"
        "SimpleLogin/app/src/main/java/io/simplelogin/android/BuildConfig.java"
        "SimpleLogin/app/src/debug/java/io/simplelogin/android/utils/Constants.kt"
        "SimpleLogin/app/src/debug/java/io/simplelogin/android/utils/Constants.java"
    )
    
    # SimpleLogin uses SLSharedPreferences for API URL configuration
    # We'll create a debug override for the default API URL
    mkdir -p "SimpleLogin/app/src/debug/java/io/simplelogin/android/utils"
    cat > "SimpleLogin/app/src/debug/java/io/simplelogin/android/utils/SLSharedPreferencesDebug.kt" << 'EOF'
package io.simplelogin.android.utils

import android.content.Context

object SLSharedPreferencesDebug {
    private const val DEFAULT_DEBUG_API_URL = "http://10.0.2.2:7777"
    
    fun setupDebugApiUrl(context: Context) {
        // Set default API URL for debug builds to local development server
        val currentUrl = SLSharedPreferences.getApiUrl(context)
        if (currentUrl == "https://app.simplelogin.io") {
            SLSharedPreferences.setApiUrl(context, DEFAULT_DEBUG_API_URL)
        }
    }
}
EOF
    
    # Update build.gradle to include network security config
    local build_gradle="SimpleLogin/app/build.gradle"
    if [[ -f "$build_gradle" ]]; then
        # Add network security config to debug build type
        if ! grep -q "networkSecurityConfig" "$build_gradle"; then
            sed -i.bak '/buildTypes {/,/}/ {
                /debug {/,/}/ {
                    /debug {/a\
            networkSecurityConfig "@xml/network_security_config"
                }
            }' "$build_gradle"
        fi
    fi
    
    cd "$SCRIPT_DIR"
    log_success "Debug build configuration completed"
}

setup_environment() {
    log_info "Setting up build environment..."
    
    # Set Java 17 - use existing JAVA_HOME if available, otherwise detect
    if [[ -n "${JAVA_HOME:-}" && -d "${JAVA_HOME:-}" ]]; then
        log_info "Using existing JAVA_HOME: $JAVA_HOME"
    elif [[ -d "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home" ]]; then
        # macOS Homebrew path
        export JAVA_HOME="/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"
        log_info "Using macOS Homebrew JAVA_HOME: $JAVA_HOME"
    elif [[ -d "/usr/lib/jvm/java-17-openjdk" ]]; then
        # Linux path
        export JAVA_HOME="/usr/lib/jvm/java-17-openjdk"
        log_info "Using Linux JAVA_HOME: $JAVA_HOME"
    else
        log_warning "Could not find Java 17 via known paths. Using system default."
        export JAVA_HOME=$(java -XshowSettings:properties -version 2>&1 | grep 'java.home' | awk '{print $3}')
    fi
    
    export PATH="$JAVA_HOME/bin:$PATH"
    log_success "Build environment configured"
}

build_app() {
    log_info "Building SimpleLogin Android app..."
    
    # Ensure codebase directory exists (for submodule approach)
    if [[ ! -d "$CODEBASE_DIR" ]]; then
        log_error "Codebase directory not found at $CODEBASE_DIR"
        log_info "This may indicate a submodule initialization issue"
        return 1
    fi
    
    if [[ ! -d "$CODEBASE_DIR/SimpleLogin" ]]; then
        log_error "SimpleLogin directory not found at $CODEBASE_DIR/SimpleLogin"
        log_info "This may indicate an incomplete submodule checkout"
        return 1
    fi
    
    cd "$CODEBASE_DIR/SimpleLogin"
    
    # Make gradlew executable
    chmod +x gradlew

    # Clean and build debug APK
    log_info "Running Gradle clean..."
    if ! ./gradlew --no-daemon clean; then
        log_error "Gradle clean failed"
        return 1
    fi

    log_info "Building F-Droid debug APK..."
    if ! ./gradlew --no-daemon assembleFdroidDebug; then
        log_error "Gradle build failed"
        return 1
    fi
    
    # Find the built F-Droid APK
    local apk_path
    apk_path=$(find app/build/outputs/apk/fdroid/debug -name "*.apk" | head -1)
    
    if [[ -z "$apk_path" || ! -f "$apk_path" ]]; then
        log_error "Built F-Droid APK not found in app/build/outputs/apk/fdroid/debug/"
        return 1
    fi
    
    log_success "APK built successfully: $apk_path"
    # Make path absolute for use from setup.sh
    local absolute_apk_path
    absolute_apk_path="$(pwd)/$apk_path"
    echo "$absolute_apk_path" > "$SCRIPT_DIR/apk_path.txt"
    
    cd "$SCRIPT_DIR"
}


verify_installation() {
    log_info "Verifying app installation..."
    
    local app_id
    app_id=$(jq -r '.app_id' "$METADATA_FILE")
    
    # Check if app is installed
    if ! adb shell pm list packages | grep -q "$app_id"; then
        log_error "App not found on device"
        return 1
    fi
    
    # Try to launch the app
    log_info "Attempting to launch app..."
    if adb shell monkey -p "$app_id" -c android.intent.category.LAUNCHER 1 > /dev/null 2>&1; then
        log_success "App launched successfully"
    else
        log_warning "App launch test failed, but this might be normal"
    fi
    
    log_success "Installation verification completed"
}

main() {
    log_info "Starting SimpleLogin Android app setup..."
    
    check_prerequisites || return 1
    # Use stock app without source modifications for real-world fidelity
    setup_environment || return 1
    build_app || return 1
    
    log_success "SimpleLogin Android app build completed successfully!"
    log_info "APK is ready for installation and testing."
}

# Run main function if script is executed directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
