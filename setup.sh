#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="${SCRIPT_DIR}/setup.log"
ANDROID_HOME="${HOME}/.android-sdk"
EMULATOR_NAME="MobileCybenchEmu"

# Default SDK version and system image
DEFAULT_SDK_VERSION=28
DEFAULT_SYSTEM_IMAGE="google_apis"

# Parse command line arguments
SDK_VERSION="$DEFAULT_SDK_VERSION"
SYSTEM_IMAGE_TYPE="$DEFAULT_SYSTEM_IMAGE"
while [[ $# -gt 0 ]]; do
    case $1 in
        --sdk)
            SDK_VERSION="$2"
            shift 2
            ;;
        --sdk=*)
            SDK_VERSION="${1#*=}"
            shift
            ;;
        --system-image)
            SYSTEM_IMAGE_TYPE="$2"
            shift 2
            ;;
        --system-image=*)
            SYSTEM_IMAGE_TYPE="${1#*=}"
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [--sdk SDK_VERSION] [--system-image SYSTEM_IMAGE_TYPE]"
            echo "  --sdk SDK_VERSION              Android SDK version to use (default: $DEFAULT_SDK_VERSION)"
            echo "  --system-image SYSTEM_IMAGE    System image type (default: $DEFAULT_SYSTEM_IMAGE)"
            echo "                                 Options: google_apis, google_apis_playstore, default, aosp_atd"
            echo "  -h, --help                     Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                                    # Use defaults (SDK $DEFAULT_SDK_VERSION, $DEFAULT_SYSTEM_IMAGE)"
            echo "  $0 --sdk 30                          # Use SDK 30 with default system image"
            echo "  $0 --system-image google_apis_playstore  # Use Play Store system image"
            echo "  $0 --sdk 29 --system-image default   # Use SDK 29 with default system image"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use -h or --help for usage information"
            exit 1
            ;;
    esac
done

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

# Detect OS and architecture
detect_os() {
    case "$(uname -s)" in
        Linux*)     echo "linux";;
        Darwin*)    echo "macos";;
        CYGWIN*|MINGW*|MSYS*) echo "windows";;
        *)          error_exit "Unsupported operating system";;
    esac
}

detect_arch() {
    case "$(uname -m)" in
        x86_64|amd64)   echo "x86_64";;
        arm64|aarch64)  echo "arm64";;
        *)              echo "x86_64";;  # Default fallback
    esac
}

# Download file with progress
download_file() {
    local url="$1"
    local output="$2"
    
    if command_exists curl; then
        curl -L --progress-bar "$url" -o "$output"
    elif command_exists wget; then
        wget --progress=bar:force "$url" -O "$output"
    else
        error_exit "Neither curl nor wget found. Please install one of them."
    fi
}

# Install Android SDK Command Line Tools
install_android_sdk() {
    local os="$1"
    log "Installing Android SDK Command Line Tools..."
    
    # Create Android SDK directory
    mkdir -p "$ANDROID_HOME"
    cd "$ANDROID_HOME"
    
    # Download SDK command line tools
    case "$os" in
        linux)
            local sdk_url="https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip"
            ;;
        macos)
            local sdk_url="https://dl.google.com/android/repository/commandlinetools-mac-11076708_latest.zip"
            ;;
        windows)
            local sdk_url="https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip"
            ;;
    esac
    
    log "Downloading Android SDK from $sdk_url"
    download_file "$sdk_url" "commandlinetools.zip"
    
    # Extract SDK tools
    if command_exists unzip; then
        unzip -q commandlinetools.zip
    else
        error_exit "unzip command not found. Please install unzip."
    fi
    
    # Organize SDK structure
    mkdir -p cmdline-tools/latest
    mv cmdline-tools/* cmdline-tools/latest/ 2>/dev/null || true
    rm commandlinetools.zip
    
    log "Android SDK Command Line Tools installed successfully"
}

# Setup environment variables
setup_environment() {
    log "Setting up environment variables..."
    
    # Add to current session
    export ANDROID_HOME="$ANDROID_HOME"
    export PATH="$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"
    
    # Add to shell profile
    local shell_profile=""
    
    # Detect the user's default shell
    local user_shell=""
    if [[ -n "$SHELL" ]]; then
        user_shell=$(basename "$SHELL")
        log "Detected user shell: $user_shell"
    fi
    
    # Set profile based on detected shell
    case "$user_shell" in
        zsh)
            shell_profile="$HOME/.zshrc"
            ;;
        bash)
            shell_profile="$HOME/.bashrc"
            ;;
        *)
            # Fallback: check which profile files exist
            if [[ -f "$HOME/.zshrc" ]]; then
                shell_profile="$HOME/.zshrc"
            elif [[ -f "$HOME/.bashrc" ]]; then
                shell_profile="$HOME/.bashrc"
            elif [[ -f "$HOME/.bash_profile" ]]; then
                shell_profile="$HOME/.bash_profile"
            else
                log "Warning: Could not detect shell or find existing profile files"
                log "Skipping shell profile configuration"
                log "User will need to manually add environment variables"
                shell_profile=""
            fi
            ;;
    esac
    
    if [[ -n "$shell_profile" ]]; then
        # Check if Android SDK environment variables already exist in the profile
        if ! grep -q "# Android SDK (added by mobile benchmark setup)" "$shell_profile" 2>/dev/null; then
            log "Adding environment variables to $shell_profile"
            {
                echo ""
                echo "# Android SDK (added by mobile benchmark setup)"
                echo "export ANDROID_HOME=\"$ANDROID_HOME\""
                echo "export PATH=\"\$ANDROID_HOME/cmdline-tools/latest/bin:\$ANDROID_HOME/platform-tools:\$ANDROID_HOME/emulator:\$PATH\""
            } >> "$shell_profile"
        else
            log "Android SDK environment variables already exist in $shell_profile"
        fi
    fi
}

# Get system image string based on architecture and system image type
get_system_image() {
    local arch="$1"
    local image_type="$2"
    
    local arch_suffix
    if [[ "$arch" == "arm64" ]]; then
        arch_suffix="arm64-v8a"
    else
        arch_suffix="x86_64"
    fi
    
    echo "system-images;android-${SDK_VERSION};${image_type};${arch_suffix}"
}

# Install required Android packages
install_android_packages() {
    local arch="$1"
    local system_image=$(get_system_image "$arch" "$SYSTEM_IMAGE_TYPE")
    
    log "Installing required Android packages for $arch architecture"
    log "SDK version: $SDK_VERSION, System image: $SYSTEM_IMAGE_TYPE"
    log "Full system image: $system_image"
    
    local sdkmanager="$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager"
    
    # Accept licenses
    yes | "$sdkmanager" --licenses >/dev/null 2>&1 || true
    
    # Install essential packages
    "$sdkmanager" \
        "platform-tools" \
        "emulator" \
        "platforms;android-${SDK_VERSION}" \
        "$system_image" \
        >/dev/null
    
    log "Android packages installed successfully"
}

# Create Android Virtual Device
create_avd() {
    local arch="$1"
    local system_image=$(get_system_image "$arch" "$SYSTEM_IMAGE_TYPE")
    
    log "Creating Android Virtual Device: $EMULATOR_NAME for $arch"
    log "SDK version: $SDK_VERSION, System image: $SYSTEM_IMAGE_TYPE"
    
    local avdmanager="$ANDROID_HOME/cmdline-tools/latest/bin/avdmanager"
    
    # Create AVD
    echo "no" | "$avdmanager" create avd \
        -n "$EMULATOR_NAME" \
        -k "$system_image" \
        -d "pixel_2" \
        --force >/dev/null
    
    # Configure AVD
    local avd_config="$HOME/.android/avd/${EMULATOR_NAME}.avd/config.ini"
    if [[ -f "$avd_config" ]]; then
        # Optimize for development
        {
            echo "hw.ramSize=2048"
            echo "hw.gpu.enabled=yes"
            echo "hw.gpu.mode=host"
            echo "hw.keyboard=yes"
            echo "showDeviceFrame=no"
            echo "skin.dynamic=yes"
        } >> "$avd_config"
    fi
    
    log "Android Virtual Device created successfully"
}

# Create helper scripts
create_helper_scripts() {
    log "Creating helper scripts..."
    
    # Start emulator script
    cat > "${SCRIPT_DIR}/start_emulator.sh" << 'EOF'
#!/bin/bash
# Start Android emulator

ANDROID_HOME="${HOME}/.android-sdk"
EMULATOR_NAME="MobileCybenchEmu"

echo "Starting Android emulator: $EMULATOR_NAME"
echo "This may take a few minutes on first boot..."

"$ANDROID_HOME/emulator/emulator" \
    -avd "$EMULATOR_NAME" \
    -no-snapshot-save \
    -wipe-data \
    -gpu host \
    -skin 1080x1920 \
    -memory 2048 \
    &

echo "Emulator started in background"
echo "Waiting for device to be ready..."

# Wait for device
"$ANDROID_HOME/platform-tools/adb" wait-for-device

echo "Device ready!"
echo "To check device status: adb devices"
EOF

    # Stop emulator script
    cat > "${SCRIPT_DIR}/stop_emulator.sh" << 'EOF'
#!/bin/bash
# Stop Android emulator

echo "Stopping Android emulator..."
adb emu kill
echo "Emulator stopped"
EOF

    # Device check script
    cat > "${SCRIPT_DIR}/check_device.sh" << 'EOF'
#!/bin/bash
# Check if Android device is ready

ANDROID_HOME="${HOME}/.android-sdk"

echo "Checking Android device status..."

# Check if ADB is available
if ! command -v adb >/dev/null 2>&1; then
    if [[ -f "$ANDROID_HOME/platform-tools/adb" ]]; then
        export PATH="$ANDROID_HOME/platform-tools:$PATH"
    else
        echo "ERROR: ADB not found. Please run setup.sh first."
        exit 1
    fi
fi

# Check for connected devices
devices=$(adb devices | grep -v "List of devices" | grep -E "device$|emulator")

if [[ -z "$devices" ]]; then
    echo "No Android devices found."
    echo "Run ./start_emulator.sh to start the emulator."
    exit 1
fi

echo "Connected devices:"
echo "$devices"

# Test device connectivity
device_id=$(echo "$devices" | head -n1 | awk '{print $1}')
echo "Testing device connectivity..."

if adb -s "$device_id" shell echo "test" >/dev/null 2>&1; then
    echo "Device is ready!"
    
    # Check Android version
    android_version=$(adb -s "$device_id" shell getprop ro.build.version.release)
    echo "Android version: $android_version"
    
    # Check architecture
    arch=$(adb -s "$device_id" shell getprop ro.product.cpu.abi)
    echo "Architecture: $arch"
    
    exit 0
else
    echo "Device connectivity test failed."
    exit 1
fi
EOF

    # Make scripts executable
    chmod +x "${SCRIPT_DIR}"/{start_emulator,stop_emulator,check_device}.sh
    
    log "Helper scripts created successfully"
}

# Main setup function
main() {
    log "Starting Android Emulator Setup"
    log "SDK version: $SDK_VERSION"
    log "System image type: $SYSTEM_IMAGE_TYPE"
    log "This script will install Android SDK and create an emulator"
    
    # Detect operating system and architecture
    local os=$(detect_os)
    local arch=$(detect_arch)
    log "Detected OS: $os"
    log "Detected architecture: $arch"
    
    # Check prerequisites
    log "Checking prerequisites..."
    
    if [[ "$os" == "linux" ]] && ! command_exists unzip; then
        error_exit "unzip is required. Install with: sudo apt-get install unzip"
    fi
    
    # Install Android SDK if not present
    if [[ ! -d "$ANDROID_HOME/cmdline-tools" ]]; then
        install_android_sdk "$os"
    else
        log "Android SDK already installed"
    fi
    
    # Setup environment
    setup_environment
    
    # Install Android packages
    install_android_packages "$arch"
    
    # Create AVD
    create_avd "$arch"
    
    # Create helper scripts
    create_helper_scripts
    
    log "Setup completed successfully!"
    echo ""
    echo "Android Emulator is ready!"
    echo ""
    echo "Configuration:"
    echo "  SDK Version: $SDK_VERSION"
    echo "  System Image: $SYSTEM_IMAGE_TYPE"
    echo "  Architecture: $arch"
    if [[ "$arch" == "arm64" ]]; then
        echo "  Note: Using ARM64 system image for Apple Silicon compatibility"
    fi
    echo ""
    echo "Next steps:"
    echo "1. Start emulator: ./start_emulator.sh"
    echo "2. Check device:   ./check_device.sh"
    echo "3. Install APKs:   adb install app.apk"
    echo ""
    echo "Useful commands:"
    echo "  ./start_emulator.sh   - Start the Android emulator"
    echo "  ./stop_emulator.sh    - Stop the Android emulator"
    echo "  ./check_device.sh     - Check device status"
    echo "  adb devices           - List connected devices"
    echo "  adb shell             - Open device shell"
    echo ""
    echo "Note: You may need to restart your terminal or run:"
    echo "  source ~/.bashrc  (or ~/.zshrc)"

    # generate agent token for host agent (if missing)
    AGENT_TOKEN_FILE="${SCRIPT_DIR}/ssh_key"
    if [[ ! -f "${AGENT_TOKEN_FILE}" ]]; then
        if command -v openssl >/dev/null 2>&1; then
            openssl rand -hex 16 > "${AGENT_TOKEN_FILE}"
        fi
        chmod 600 "${AGENT_TOKEN_FILE}"
        log "Wrote host agent token -> ${AGENT_TOKEN_FILE}"
    else
        log "Host agent token exists -> ${AGENT_TOKEN_FILE}"
    fi
    MCB_AGENT_PORT=52888
    if (echo > /dev/tcp/127.0.0.1/${MCB_AGENT_PORT}) >/dev/null 2>&1; then
        log "Intermediary server already running on ${MCB_AGENT_PORT}. Killing server..."
        pkill -f host_agent.py || true
    fi
    nohup python3 "${SCRIPT_DIR}/host_agent.py" > "${HOME}/mobilecybench-agent.out" 2>&1 &
    log "Started mobilecybench host intermediary on port ${MCB_AGENT_PORT}"
}

# Run main function
main "$@"