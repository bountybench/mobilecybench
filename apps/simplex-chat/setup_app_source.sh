#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="${SCRIPT_DIR}/setup_app_source.log"

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Error handling
error_exit() {
    log "ERROR: $1"
    exit 1
}

# Check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check Java installation
check_java() {
    log "Checking Java installation..."

    if ! command_exists java; then
        error_exit "Java is not installed. Please install OpenJDK 17 or newer"
    fi

    # Get Java version
    local java_version=$(java -version 2>&1 | head -n1 | cut -d'"' -f2 | cut -d'.' -f1)

    # Handle Java version format (8, 11, 17, etc.)
    if [[ "$java_version" =~ ^1\. ]]; then
        java_version=$(echo "$java_version" | cut -d'.' -f2)
    fi

    log "Detected Java version: $java_version"

    if [[ $java_version -lt 17 ]]; then
        error_exit "Java $java_version is too old. Android SDK requires Java 17 or newer"
    fi

    log "Java $java_version is compatible"
}

# Check and install build dependencies
install_build_dependencies() {
    log "Checking build dependencies..."

    # Check for required tools
    local missing_tools=()

    if ! command_exists git; then
        missing_tools+=("git")
    fi

    if ! command_exists make; then
        missing_tools+=("build-essential")
    fi

    if ! command_exists pkg-config; then
        missing_tools+=("pkg-config")
    fi

    # Check for Haskell Stack (required for SimpleX server components)
    if ! command_exists stack; then
        log "Installing Haskell Stack..."
        curl -sSL https://get.haskellstack.org/ | sh
        export PATH="$HOME/.local/bin:$PATH"
    fi

    # Check for Rust (required for some crypto components)
    if ! command_exists rustc; then
        log "Installing Rust..."
        curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
        source "$HOME/.cargo/env"
    fi

    if [[ ${#missing_tools[@]} -gt 0 ]]; then
        log "ERROR: Missing required tools: ${missing_tools[*]}"
        log ""
        log "Please install them manually using one of these methods:"
        log ""

        if command_exists apt-get; then
            log "On Ubuntu/Debian:"
            log "  sudo apt-get update"
            for tool in "${missing_tools[@]}"; do
                log "  sudo apt-get install -y $tool"
            done
        elif command_exists brew; then
            log "On macOS with Homebrew:"
            for tool in "${missing_tools[@]}"; do
                # Map Linux package names to macOS equivalents
                case "$tool" in
                    "build-essential")
                        log "  xcode-select --install  # For build tools"
                        ;;
                    *)
                        log "  brew install $tool"
                        ;;
                esac
            done
        else
            log "Please install these tools using your system's package manager"
        fi
        log ""
        error_exit "Missing required dependencies"
    fi
}

# Build native libraries (libsimplex.so and libsupport.so)
build_native_libraries() {
	echo "Building native libraries"
	gzip -d ${SCRIPT_DIR}/codebase/apps/multiplatform/common/src/commonMain/cpp/android/libs/arm64-v8a/libsimplex.so.gz
	gzip -d ${SCRIPT_DIR}/codebase/apps/multiplatform/common/src/commonMain/cpp/android/libs/armeabi-v7a/libsimplex.so.gz
	echo "Built native libraries"
}
# build_native_libraries() {
#     log "Building native libraries (libsimplex.so and libsupport.so)..."
# 
#     local source_dir="${SCRIPT_DIR}/codebase"
#     local multiplatform_dir="${source_dir}/apps/multiplatform"
#     local libs_folder="${multiplatform_dir}/common/src/commonMain/cpp/android/libs"
# 
#     # Check if Nix is available
#     if ! command_exists nix; then
#         log "WARNING: Nix is not installed. Attempting to build without native libraries..."
#         log "Native libraries may need to be provided separately."
#         return 0
#     fi
# 
#     # Check if running on macOS - attempt to build anyway
#     if [[ "$(uname -s)" == "Darwin" ]]; then
#         log "INFO: Running on macOS. Will attempt to cross-compile Android libraries using Nix."
#         log "If this fails, you can use Docker/Colima to build on Linux."
#         log "See: https://github.com/simplex-chat/simplex-chat for build instructions"
#         # Continue with the build attempt
#     fi
# 
#     cd "$source_dir"
# 
#     # Build for arm64-v8a (aarch64)
#     local arch="aarch64"
#     local android_arch="arm64-v8a"
# 
#     log "Building libraries for ${android_arch}..."
# 
#     # Detect the build system (x86_64-linux, x86_64-darwin, aarch64-darwin, etc.)
#     local nix_system
#     if [[ "$(uname -s)" == "Darwin" ]]; then
#         if [[ "$(uname -m)" == "arm64" ]]; then
#             nix_system="aarch64-darwin"
#         else
#             nix_system="x86_64-darwin"
#         fi
#     else
#         nix_system="x86_64-linux"
#     fi
# 
#     log "Detected Nix system: ${nix_system}"
# 
#     local android_simplex_lib="${source_dir}#hydraJobs.${nix_system}.${arch}-android:lib:simplex-chat"
#     local android_support_lib="${source_dir}#hydraJobs.${nix_system}.${arch}-android:lib:support"
# 
#     # Create libs directory
#     mkdir -p "$libs_folder/$android_arch"
# 
#     # Build libsimplex.so
#     log "Building libsimplex.so for ${android_arch}... (this may take 30+ minutes on first build)"
#     if nix --extra-experimental-features "nix-command flakes" build "$android_simplex_lib" --out-link "${SCRIPT_DIR}/result-libsimplex-${arch}" 2>&1 | tee -a "$LOG_FILE"; then
#         local simplex_output="${SCRIPT_DIR}/result-libsimplex-${arch}/pkg-${arch}-android-libsimplex.zip"
#         if [[ -f "$simplex_output" ]]; then
#             unzip -o "$simplex_output" -d "$libs_folder/$android_arch"
#             log "libsimplex.so built and extracted successfully"
#         else
#             log "WARNING: libsimplex.so build output not found at expected location: $simplex_output"
#             log "Checking for alternative output locations..."
#             find "${SCRIPT_DIR}/result-libsimplex-${arch}" -name "*.zip" -o -name "*.so" | tee -a "$LOG_FILE"
#         fi
#     else
#         log "ERROR: Failed to build libsimplex.so"
#         log "This is likely because Android cross-compilation from macOS is not fully supported."
#         log "Please use Docker/Colima to build on Linux, or download prebuilt libraries."
#         return 1
#     fi
# 
#     # Build libsupport.so
#     log "Building libsupport.so for ${android_arch}..."
#     if nix --extra-experimental-features "nix-command flakes" build "$android_support_lib" --out-link "${SCRIPT_DIR}/result-libsupport-${arch}" 2>&1 | tee -a "$LOG_FILE"; then
#         local support_output="${SCRIPT_DIR}/result-libsupport-${arch}/pkg-${arch}-android-libsupport.zip"
#         if [[ -f "$support_output" ]]; then
#             unzip -o "$support_output" -d "$libs_folder/$android_arch"
#             log "libsupport.so built and extracted successfully"
#         else
#             log "WARNING: libsupport.so build output not found at expected location: $support_output"
#             log "Checking for alternative output locations..."
#             find "${SCRIPT_DIR}/result-libsupport-${arch}" -name "*.zip" -o -name "*.so" | tee -a "$LOG_FILE"
#         fi
#     else
#         log "ERROR: Failed to build libsupport.so"
#         log "This is likely because Android cross-compilation from macOS is not fully supported."
#         log "Please use Docker/Colima to build on Linux, or download prebuilt libraries."
#         return 1
#     fi
# 
#     # Verify libraries were built
#     if [[ -f "$libs_folder/$android_arch/libsimplex.so" ]] && [[ -f "$libs_folder/$android_arch/libsupport.so" ]]; then
#         log "Native libraries built successfully!"
#     else
#         log "WARNING: Native libraries may not have been built correctly"
#         log "You may need to manually build them using: scripts/android/build-android.sh"
#     fi
# }

# Build SimpleX Chat from source
build_simplex_chat() {
    log "Building SimpleX Chat from source..."

    local source_dir="${SCRIPT_DIR}/codebase"
    local app_dir="${SCRIPT_DIR}"
    local apk_dir="$app_dir/apk"

    # Create directories
    mkdir -p "$apk_dir"

    # Check if source exists
    if [[ ! -d "$source_dir" ]]; then
        error_exit "SimpleX Chat source not found at $source_dir"
    fi

    # Build native libraries first
    build_native_libraries

    cd "$source_dir"

    # Get commit version for metadata
    local commit_version=$(git rev-parse --short HEAD)
    log "Building from commit: $commit_version"

    # Build native dependencies first
    log "Building native Haskell components..."
    cd "${source_dir}"

    # Build the simplexmq library that the Android app depends on
    if [[ -f "Makefile" ]]; then
        make android-deps || log "Warning: Android dependencies build failed or not required"
    fi

    # Build Android app
    log "Building Android APK..."
    cd "${source_dir}/apps/multiplatform"

    # Set up Android environment
    export ANDROID_HOME="${HOME}/.android-sdk"
    export PATH="$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/build-tools/34.0.0:$PATH"

	echo $ANDROID_HOME

	log "Got to this point"
	# yes | sdkmanager --licenses
    # Clean previous builds
    ./gradlew clean --stacktrace -Dorg.gradle.jvmargs="--enable-native-access=ALL-UNNAMED" || error_exit "Gradle clean failed"

    # Build release APK
    log "Building release APK (this may take 10-20 minutes)..."
    ./gradlew :android:assembleRelease -Dorg.gradle.jvmargs="--enable-native-access=ALL-UNNAMED" || error_exit "APK build failed"

    # Find the built APK
    local built_apk=$(find . -name "*release*.apk" -type f | head -n1)

    if [[ -z "$built_apk" || ! -f "$built_apk" ]]; then
        error_exit "Built APK not found"
    fi

    log "Found built APK: $built_apk"

    # Copy APK to expected location
    local target_apk="${apk_dir}/simplex-chat.apk"
    cp "$built_apk" "$target_apk"

    log "APK copied to: $target_apk"

    # Verify APK
    if [[ -f "$target_apk" ]]; then
        local apk_size=$(du -h "$target_apk" | cut -f1)
        log "SimpleX Chat APK built successfully (size: $apk_size)"

        # Show APK info
        if command_exists aapt; then
            log "APK information:"
            aapt dump badging "$target_apk" | head -n5 || true
        fi

        return 0
    else
        error_exit "Failed to copy APK to target location"
    fi
}

# Create signing key if needed
create_signing_key() {
    local keystore_path="${SCRIPT_DIR}/codebase/debug.keystore"

    if [[ ! -f "$keystore_path" ]]; then
        log "Creating debug signing key..."
        keytool -genkey -v -keystore "$keystore_path" -alias androiddebugkey \
            -keyalg RSA -keysize 2048 -validity 10000 \
            -dname "CN=Debug,OU=Debug,O=Debug,L=Debug,S=Debug,C=US" \
            -storepass android -keypass android
    fi
}

# Main function
main() {
    log "Starting SimpleX Chat build from source"

    # Check prerequisites
    check_java
    install_build_dependencies

    # Create signing key
    create_signing_key

    # Build the app
    build_simplex_chat

    log "SimpleX Chat build completed successfully!"
    echo ""
    echo "APK Location: apps/simplex-chat/apk/simplex-chat.apk"
    echo ""
    echo "Next steps:"
    echo "1. Run ./setup.sh to set up the emulator and install the APK"
    echo "2. Or manually install with: adb install apps/simplex-chat/apk/simplex-chat.apk"
}

# Run main function
main "$@"
