#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="${SCRIPT_DIR}/setup.log"
ANDROID_HOME="${HOME}/.android-sdk"
EMULATOR_NAME="MobileCybenchEmu"
SNAPSHOT_NAME="golden"

# Default SDK version
DEFAULT_SDK_VERSION=28

# Parse command line arguments
SDK_VERSION="$DEFAULT_SDK_VERSION"
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
        -h|--help)
            echo "Usage: $0 [--sdk SDK_VERSION]"
            echo "  --sdk SDK_VERSION    Android SDK version to use (default: $DEFAULT_SDK_VERSION)"
            echo "  -h, --help          Show this help message"
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
    if [[ -n "$ZSH_VERSION" ]]; then
        shell_profile="$HOME/.zshrc"
    elif [[ -n "$BASH_VERSION" ]]; then
        shell_profile="$HOME/.bashrc"
    fi
    
    if [[ -n "$shell_profile" ]]; then
        log "Adding environment variables to $shell_profile"
        {
            echo ""
            echo "# Android SDK (added by mobile benchmark setup)"
            echo "export ANDROID_HOME=\"$ANDROID_HOME\""
            echo "export PATH=\"\$ANDROID_HOME/cmdline-tools/latest/bin:\$ANDROID_HOME/platform-tools:\$ANDROID_HOME/emulator:\$PATH\""
        } >> "$shell_profile"
    fi
}

# Install required Android packages
install_android_packages() {
    local arch="$1"
    log "Installing required Android packages for $arch architecture (SDK version: $SDK_VERSION)..."
    
    local sdkmanager="$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager"
    
    # Accept licenses
    yes | "$sdkmanager" --licenses >/dev/null 2>&1 || true
    
    # Determine system image based on architecture
    local system_image
    if [[ "$arch" == "arm64" ]]; then
        system_image="system-images;android-${SDK_VERSION};google_apis;arm64-v8a"
    else
        system_image="system-images;android-${SDK_VERSION};google_apis;x86_64"
    fi
    
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
    log "Creating Android Virtual Device: $EMULATOR_NAME for $arch (SDK version: $SDK_VERSION)"
    
    local avdmanager="$ANDROID_HOME/cmdline-tools/latest/bin/avdmanager"
    
    # Determine system image based on architecture
    local system_image
    if [[ "$arch" == "arm64" ]]; then
        system_image="system-images;android-${SDK_VERSION};google_apis;arm64-v8a"
    else
        system_image="system-images;android-${SDK_VERSION};google_apis;x86_64"
    fi
    
    # Create AVD
    echo "no" | "$avdmanager" create avd \
        -n "$EMULATOR_NAME" \
        -k "$system_image" \
        -d "pixel_2" \
        --force >/dev/null
    
    # Configure AVD
    local avd_config="$HOME/.android/avd/${EMULATOR_NAME}.avd/config.ini"
    if [[ -f "$avd_config" ]]; then
        # Optimize for development and enable snapshots
        {
            echo "hw.ramSize=2048"
            echo "hw.gpu.enabled=yes"
            echo "hw.gpu.mode=host"
            echo "hw.keyboard=yes"
            echo "showDeviceFrame=no"
            echo "skin.dynamic=yes"
            echo "disk.dataPartition.size=2G"
            echo "fastboot.forceColdBoot=no"
            echo "snapshot.present=true"
        } >> "$avd_config"
    fi
    
    log "Android Virtual Device created successfully"
}

# Install Frida-server
install_frida_server() {
    local arch="$1"
    log "Installing Frida-server..."
    
    # Determine Frida-server binary based on architecture
    local frida_version="16.5.5"  # Use a stable version
    local frida_url
    if [[ "$arch" == "arm64" ]]; then
        frida_url="https://github.com/frida/frida/releases/download/${frida_version}/frida-server-${frida_version}-android-arm64.xz"
    else
        frida_url="https://github.com/frida/frida/releases/download/${frida_version}/frida-server-${frida_version}-android-x86_64.xz"
    fi
    
    # Download Frida-server
    local frida_binary="frida-server.xz"
    log "Downloading Frida-server from $frida_url"
    download_file "$frida_url" "$frida_binary"
    
    # Extract and prepare Frida-server
    if command_exists xz; then
        xz -d "$frida_binary"
    else
        error_exit "xz command not found. Please install xz-utils."
    fi
    
    local frida_server_binary="${frida_binary%.xz}"
    chmod +x "$frida_server_binary"
    
    # Start emulator with writable system
    log "Starting emulator to install Frida-server..."
    "$ANDROID_HOME/emulator/emulator" \
        -avd "$EMULATOR_NAME" \
        -writable-system \
        -no-snapshot \
        -wipe-data \
        -gpu host \
        -skin 1080x1920 \
        -memory 2048 \
        &> "${SCRIPT_DIR}/emulator.log" &
    local emulator_pid=$!
    
    # Wait for emulator to boot
    log "Waiting for emulator to boot..."
    "$ANDROID_HOME/platform-tools/adb" wait-for-device
    sleep 10  # Additional wait for system stability
    
    # Remount system as writable
    log "Remounting system as writable..."
    "$ANDROID_HOME/platform-tools/adb" root
    "$ANDROID_HOME/platform-tools/adb" remount
    
    # Push Frida-server to emulator
    log "Pushing Frida-server to emulator..."
    "$ANDROID_HOME/platform-tools/adb" push "$frida_server_binary" /data/local/tmp/frida-server
    
    # Set permissions and start Frida-server
    "$ANDROID_HOME/platform-tools/adb" shell "chmod 755 /data/local/tmp/frida-server"
    "$ANDROID_HOME/platform-tools/adb" shell "/data/local/tmp/frida-server &"
    
    # Verify Frida-server is running
    sleep 5
    if "$ANDROID_HOME/platform-tools/adb" shell "ps | grep frida-server" >/dev/null; then
        log "Frida-server installed and running"
    else
        error_exit "Failed to start Frida-server"
    fi
    
    # Clean up
    rm "$frida_server_binary"
}

# Install mitmproxy CA certificate
install_mitmproxy_ca() {
    log "Installing mitmproxy CA certificate..."
    
    # Generate mitmproxy CA certificate if not present
    local mitmproxy_dir="$HOME/.mitmproxy"
    local mitm_ca_file="$mitmproxy_dir/mitmproxy-ca-cert.pem"
    
    if [[ ! -f "$mitm_ca_file" ]]; then
        if command_exists mitmproxy; then
            log "Generating mitmproxy CA certificate..."
            mitmproxy --set confdir="$mitmproxy_dir" >/dev/null 2>&1
        else
            error_exit "mitmproxy not found. Please install mitmproxy (e.g., pip install mitmproxy)."
        fi
    fi
    
    # Convert certificate to Android-compatible format
    local cert_hash=$(openssl x509 -inform PEM -subject_hash_old -in "$mitm_ca_file" 2>/dev/null | head -1)
    local cert_file="${cert_hash}.0"
    
    log "Converting mitmproxy CA certificate for Android..."
    openssl x509 -inform PEM -text -in "$mitm_ca_file" -out "$cert_file" >/dev/null
    
    # Push certificate to emulator (emulator already running from Frida installation)
    log "Pushing mitmproxy CA certificate to emulator..."
    "$ANDROID_HOME/platform-tools/adb" push "$cert_file" /system/etc/security/cacerts/"$cert_file"
    
    # Set permissions
    "$ANDROID_HOME/platform-tools/adb" shell "chmod 644 /system/etc/security/cacerts/$cert_file"
    
    # Verify certificate installation
    if "$ANDROID_HOME/platform-tools/adb" shell "ls /system/etc/security/cacerts/$cert_file" >/dev/null; then
        log "mitmproxy CA certificate installed successfully"
    else
        error_exit "Failed to install mitmproxy CA certificate"
    fi
    
    # Clean up
    rm "$cert_file"
}

# Save golden snapshot
save_golden_snapshot() {
    log "Saving golden snapshot..."
    
    # Save snapshot
    "$ANDROID_HOME/platform-tools/adb" emu avd snapshot save "$SNAPSHOT_NAME"
    
    # Verify snapshot
    if "$ANDROID_HOME/emulator/emulator" -avd "$EMULATOR_NAME" -list-snapshots | grep -q "$SNAPSHOT_NAME"; then
        log "Golden snapshot saved successfully"
    else
        error_exit "Failed to save golden snapshot"
    fi
    
    # Stop emulator
    log "Stopping emulator..."
    "$ANDROID_HOME/platform-tools/adb" emu kill
    wait
}

# Create helper scripts
create_helper_scripts() {
    log "Creating helper scripts..."
    
    # Start emulator script with snapshot
    cat > "${SCRIPT_DIR}/start_emulator.sh" << EOF
#!/bin/bash
# Start Android emulator with golden snapshot

ANDROID_HOME="\${HOME}/.android-sdk"
EMULATOR_NAME="MobileCybenchEmu"
SNAPSHOT_NAME="$SNAPSHOT_NAME"

echo "Starting Android emulator: \$EMULATOR_NAME with snapshot: \$SNAPSHOT_NAME"
echo "This may take a few minutes..."

"\$ANDROID_HOME/emulator/emulator" \\
    -avd "\$EMULATOR_NAME" \\
    -snapshot "\$SNAPSHOT_NAME" \\
    -no-snapshot-save \\
    -gpu host \\
    -skin 1080x1920 \\
    -memory 2048 \\
    &

echo "Emulator started in background"
echo "Waiting for device to be ready..."

# Wait for device
"\$ANDROID_HOME/platform-tools/adb" wait-for-device

# Verify Frida-server is running
if "\$ANDROID_HOME/platform-tools/adb" shell "ps | grep frida-server" >/dev/null; then
    echo "Frida-server is running"
else
    echo "WARNING: Frida-server is not running"
fi

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
    
    # Check Frida-server
    if adb -s "$device_id" shell "ps | grep frida-server" >/dev/null; then
        echo "Frida-server: Running"
    else
        echo "Frida-server: Not running"
    fi
    
    # Check mitmproxy CA certificate
    if adb -s "$device_id" shell "ls /system/etc/security/cacerts" | grep -E '[0-9a-f]{8}\.0' >/dev/null; then
        echo "mitmproxy CA certificate: Installed"
    else
        echo "mitmproxy CA certificate: Not installed"
    fi
    
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
    log "Starting Android Emulator Setup (SDK version: $SDK_VERSION)"
    log "This script will install Android SDK, create an emulator, and configure Frida and mitmproxy"
    
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
    if ! command_exists xz; then
        error_exit "xz is required. Install with: sudo apt-get install xz-utils"
    fi
    if ! command_exists openssl; then
        error_exit "openssl is required. Install with: sudo apt-get install openssl"
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
    
    # Install Frida-server and mitmproxy CA certificate
    install_frida_server "$arch"
    install_mitmproxy_ca
    
    # Save golden snapshot
    save_golden_snapshot
    
    # Create helper scripts
    create_helper_scripts
    
    log "Setup completed successfully!"
    echo ""
    echo "Android Emulator is ready with Frida and mitmproxy!"
    echo ""
    echo "SDK Version: $SDK_VERSION"
    echo "Architecture: $arch"
    if [[ "$arch" == "arm64" ]]; then
        echo "Note: Using ARM64 system image for Apple Silicon compatibility"
    fi
    echo ""
    echo "Next steps:"
    echo "1. Start emulator: ./start_emulator.sh"
    echo "2. Check device:   ./check_device.sh"
    echo "3. Install APKs:   adb install app.apk"
    echo ""
    echo "Useful commands:"
    echo "  ./start_emulator.sh   - Start the Android emulator with golden snapshot"
    echo "  ./stop_emulator.sh    - Stop the Android emulator"
    echo "  ./check_device.sh     - Check device status"
    echo "  adb devices           - List connected devices"
    echo "  adb shell             - Open device shell"
    echo ""
    echo "Note: You may need to restart your terminal or run:"
    echo "  source ~/.bashrc  (or ~/.zshrc)"
}

# Run main function
main "$@"