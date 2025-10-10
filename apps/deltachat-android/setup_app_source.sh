#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"

ANDROID_HOME="${HOME}/Android/Sdk"
source "$ROOT_DIR/utils/android.sh"

LOG_PREFIX="[deltachat_setup_app_source]"
info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*"; }
error(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*"; exit 1; }

# Install Rust Android targets early, right after function definitions
info "Installing Rust Android targets early..."
if command -v rustup >/dev/null 2>&1; then
    if ! rustup target add aarch64-linux-android armv7-linux-androideabi i686-linux-android x86_64-linux-android; then
        error "Failed to install Rust Android targets"
    fi
    info "Rust Android targets installed successfully"
else
    error "rustup not found - Rust toolchain required"
fi

check_prerequisites() {
    info "Checking prerequisites..."
    
    if ! command -v java >/dev/null 2>&1; then
        error "Java not found. Please install Java 17."
    fi
    
    if ! command -v rustc >/dev/null 2>&1; then
        error "Rust not found. Please install Rust toolchain."
    fi
    
    if [[ ! -d "$ANDROID_HOME" && -d "/usr/local/lib/android/sdk" ]]; then
        ANDROID_HOME="/usr/local/lib/android/sdk"
    fi
    
    if [[ ! -d "$ANDROID_HOME" ]]; then
        error "Android SDK not found at $ANDROID_HOME"
    fi
    
    if [[ ! -d "$ANDROID_HOME/ndk" ]]; then
        error "Android NDK not found. Please install NDK 27.1.12297006"
    fi
    
    info "Prerequisites verified."
}

setup_environment() {
    info "Setting up build environment..."
    
    if [[ -d "/opt/homebrew/opt/openjdk@17" ]]; then
        export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
    elif [[ -d "/usr/lib/jvm/java-17-openjdk" ]]; then
        export JAVA_HOME=/usr/lib/jvm/java-17-openjdk
    elif command -v /usr/libexec/java_home &>/dev/null; then
        export JAVA_HOME="$(/usr/libexec/java_home -v 17)"
    else
        export JAVA_HOME=$(java -XshowSettings:properties -version 2>&1 | grep 'java.home' | awk '{print $3}')
    fi
    
    export PATH="$JAVA_HOME/bin:$PATH"
    
    export ANDROID_HOME="$ANDROID_HOME"
    export ANDROID_NDK_HOME="$ANDROID_HOME/ndk/27.1.12297006"
    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
    
    echo "sdk.dir=$ANDROID_HOME" > local.properties
    echo "ndk.dir=$ANDROID_NDK_HOME" >> local.properties
    
    info "Environment configured."
}

patch_gradle_config() {
    info "Patching Gradle configuration..."
    
    if [[ -f "gradle.properties" ]]; then
        sed -i.bak \
            -e 's/^org.gradle.jvmargs=.*/org.gradle.jvmargs=-Xmx4608m -XX:MaxMetaspaceSize=1024m -XX:+UseParallelGC/' \
            gradle.properties
    fi
}

build_rust_core() {
    info "Building DeltaChat Rust core..."
    
    git submodule update --init --recursive
    
    ./scripts/ndk-make.sh
    
    info "Rust core build completed."
}

build_deltachat() {
    info "Building DeltaChat Android from source..."
    
    local temp_out=$(mktemp)
    local temp_err=$(mktemp)
    
    if ./gradlew assembleFossDebug --no-daemon --parallel > "$temp_out" 2> "$temp_err"; then
        info "Build completed successfully."
        rm -f "$temp_out" "$temp_err"
    else
        local exit_code=$?
        error "Build failed with exit code $exit_code"
        
        if [[ -s "$temp_err" ]]; then
            echo "Error output:"
            cat "$temp_err"
        fi
        
        if [[ -s "$temp_out" ]]; then
            echo "Last 50 lines of build output:"
            tail -50 "$temp_out"
        fi
        
        rm -f "$temp_out" "$temp_err"
        exit $exit_code
    fi
}

main() {
    info "DeltaChat Android Setup"
    echo "======================"
    
    CODEBASE_DIR="$SCRIPT_DIR/codebase"
    if [[ ! -d "$CODEBASE_DIR" ]]; then
        error "DeltaChat codebase directory not found at $CODEBASE_DIR"
    fi
    
    cd "$CODEBASE_DIR"
    
    if [[ ! -f "gradlew" ]]; then
        error "gradlew not found in codebase directory."
    fi
    
    check_prerequisites
    setup_environment
    patch_gradle_config
    build_rust_core
    build_deltachat
    
    echo ""
    echo "Setup complete! DeltaChat is ready for installation."
}

main "$@"
