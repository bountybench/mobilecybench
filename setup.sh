#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="${SCRIPT_DIR}/setup.log"
ANDROID_HOME="${HOME}/.android-sdk"
EMULATOR_NAME="MobileCybenchEmu"

# Default SDK version and system image
DEFAULT_SDK_VERSION=35
DEFAULT_SYSTEM_IMAGE="google_apis"

# Load app metadata if app name provided
load_app_metadata() {
    local app_name="$1"
    local metadata_file="${SCRIPT_DIR}/apps/${app_name}/metadata.json"
    
    if [[ -f "$metadata_file" ]]; then
        local validation_result=$(python3 -c "
import json, sys
try:
    data = json.load(open('$metadata_file'))
    sdk = data.get('sdk', '')
    # TODO: Support SDK 36 once system images are released
    if sdk and str(sdk).isdigit() and 21 <= int(sdk) <= 35:
        print(f'VALID:{sdk}')
    else:
        print('INVALID')
except:
    print('INVALID')
" 2>/dev/null)
        
        if [[ "$validation_result" =~ ^VALID: ]]; then
            echo "${validation_result#VALID:}"
        else
            echo "INVALID"
        fi
    else
        echo "MISSING"
    fi
}

# Warn user about old SDK versions and ask for confirmation
warn_old_sdk_version() {
    local sdk_version="$1"
    local context="${2:-Android SDK}"  
    
    if [[ $sdk_version -lt 30 ]]; then
        echo "Warning: $context $sdk_version is quite old."
        echo "Old SDK versions may have compatibility issues with modern devices."
        read -p "Are you sure you want to proceed? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Setup cancelled."
            exit 0
        fi
    fi
}

# Parse command line arguments
APP_NAME=""
SDK_VERSION="$DEFAULT_SDK_VERSION"
SYSTEM_IMAGE_TYPE="$DEFAULT_SYSTEM_IMAGE"

# Check if first argument is an app name (no dashes, exists in apps/ directory with valid metadata)
if [[ $# -gt 0 && "$1" != -* && -d "${SCRIPT_DIR}/apps/$1" ]]; then
    APP_NAME="$1"
    SDK_VERSION=$(load_app_metadata "$APP_NAME")
    
    # Validate metadata
    if [[ "$SDK_VERSION" == "MISSING" ]]; then
        echo "Error: App '$APP_NAME' has no metadata.json file"
        exit 1
    elif [[ "$SDK_VERSION" == "INVALID" ]]; then
        echo "Error: App '$APP_NAME' has invalid or missing SDK version in metadata.json"
        echo "SDK must be a number between 21-35"
        exit 1
    fi
    
    SYSTEM_IMAGE_TYPE="$DEFAULT_SYSTEM_IMAGE"
    
    warn_old_sdk_version "$SDK_VERSION" "App '$APP_NAME' uses Android SDK"
else
    # Standard flag parsing mode
    while [[ $# -gt 0 ]]; do
        case $1 in
            --sdk)
                SDK_VERSION="$2"
                warn_old_sdk_version "$SDK_VERSION"
                shift 2
                ;;
            --sdk=*)
                SDK_VERSION="${1#*=}"
                warn_old_sdk_version "$SDK_VERSION"
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
                echo "Usage: $0"
                echo "   or: $0 APP_NAME"
                echo "   or: $0 [--sdk SDK_VERSION] [--system-image SYSTEM_IMAGE_TYPE]"
                echo ""
                echo "Mode 1: Use defaults (SDK $DEFAULT_SDK_VERSION, $DEFAULT_SYSTEM_IMAGE)"
                echo "Mode 2: Auto-configure from app metadata (Recommended)"
                echo "Mode 3: Manual SDK and system image configuration"
                echo ""
                echo "Arguments:"
                echo "  APP_NAME                       App name from apps/ directory (uses SDK from metadata)"
                echo "  --sdk SDK_VERSION              Android SDK version (default: $DEFAULT_SDK_VERSION)"
                echo "  --system-image SYSTEM_IMAGE    System image type (default: $DEFAULT_SYSTEM_IMAGE)"
                echo "  -h, --help                     Show this help message"
                echo ""
                echo "Available apps:"
                if [[ -d "${SCRIPT_DIR}/apps" ]]; then
                    for app_dir in "${SCRIPT_DIR}/apps"/*; do
                        if [[ -d "$app_dir" && -f "$app_dir/metadata.json" ]]; then
                            app_name=$(basename "$app_dir")
                            app_sdk=$(python3 -c "import json; data=json.load(open('$app_dir/metadata.json')); print(data.get('sdk', 'N/A'))" 2>/dev/null || echo "N/A")
                            echo "  $app_name (SDK $app_sdk)"
                        fi
                    done
                fi
                echo ""
                echo "Examples:"
                echo "  $0                                    # Use defaults (SDK $DEFAULT_SDK_VERSION, $DEFAULT_SYSTEM_IMAGE)"
                echo "  $0 conversations                      # Use conversations app (SDK 35, google_apis)"
                echo "  $0 owncloud-android                   # Use owncloud-android app (SDK 34, google_apis)"
                echo "  $0 wordpress                          # Use wordpress app (SDK 35, google_apis)"
                echo "  $0 --sdk 30                           # Use SDK 30 with default system image"
                exit 0
                ;;
            *)
                echo "Unknown option: $1"
                echo "Available apps:"
                if [[ -d "${SCRIPT_DIR}/apps" ]]; then
                    for app_dir in "${SCRIPT_DIR}/apps"/*; do
                        if [[ -d "$app_dir" && -f "$app_dir/metadata.json" ]]; then
                            echo "  $(basename "$app_dir")"
                        fi
                    done
                fi
                echo "Use -h or --help for usage information"
                exit 1
                ;;
        esac
    done
fi

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

# Check Java installation and version
check_java() {
    log "Checking Java installation..."
    
    if ! command_exists java; then
        error_exit "Java is not installed. Please install OpenJDK 17 or newer:
        sudo apt install -y openjdk-17-jdk
        
        Then set JAVA_HOME:
        export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64"
    fi
    
    # Get Java version
    local java_version=$(java -version 2>&1 | head -n1 | cut -d'"' -f2 | cut -d'.' -f1)
    
    # Handle Java version format (8, 11, 17, etc.)
    if [[ "$java_version" =~ ^1\. ]]; then
        java_version=$(echo "$java_version" | cut -d'.' -f2)
    fi
    
    log "Detected Java version: $java_version"
    
    if [[ $java_version -lt 17 ]]; then
        error_exit "Java $java_version is too old. Android SDK requires Java 17 or newer.
        Please install OpenJDK 17:
        sudo apt install -y openjdk-17-jdk
        
        Then set JAVA_HOME:
        export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
        export PATH=\$JAVA_HOME/bin:\$PATH"
    fi
    
    log "Java $java_version is compatible with Android SDK"
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
    
    # Fix path for Windows MinGW users
    if [[ "$OSTYPE" == "msys" ]]; then
        {
            sdkmanager="$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager.bat"
        }
    fi
    
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

    # Fix path for Windows MinGW users
    if [[ "$OSTYPE" == "msys" ]]; then
        {
            avdmanager="$ANDROID_HOME/cmdline-tools/latest/bin/avdmanager.bat"
        }
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

# Check if emulator is already running
check_running_emulator() {
    local running_emulators
    if command -v adb >/dev/null 2>&1; then
        running_emulators=$(adb devices | grep -E "emulator-[0-9]+.*device$" | wc -l)
    elif [[ -f "$ANDROID_HOME/platform-tools/adb" ]]; then
        running_emulators=$("$ANDROID_HOME/platform-tools/adb" devices | grep -E "emulator-[0-9]+.*device$" | wc -l)
    else
        echo "Warning: ADB not found, cannot check for running emulators"
        return 0
    fi
    
    if [[ $running_emulators -gt 0 ]]; then
        echo "Warning: There are $running_emulators Android emulator(s) already running."
        echo "Starting another emulator may cause performance issues or conflicts."
        echo ""
        echo "Current running emulators:"
        if command -v adb >/dev/null 2>&1; then
            adb devices | grep -E "emulator-[0-9]+.*device$"
        else
            "$ANDROID_HOME/platform-tools/adb" devices | grep -E "emulator-[0-9]+.*device$"
        fi
        echo ""
        read -p "Do you want to proceed anyway? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Emulator start cancelled."
            echo "To stop the currently running emulators, you can use: ./stop_emulator.sh"
            exit 0
        fi
    fi
}

# Check for running emulators before starting
check_running_emulator

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
    
    # Check SDK version (API level)
    sdk_version=$(adb -s "$device_id" shell getprop ro.build.version.sdk)
    echo "SDK version (API level): $sdk_version"
    
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
    pip install -e .

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
    
    # Check Java installation and version
    check_java
    
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

    
    # generate token for host agent
    BRIDGE_TOKEN_FILE="${SCRIPT_DIR}/ssh_key"
    if [[ ! -f "${BRIDGE_TOKEN_FILE}" ]]; then
        if command -v openssl >/dev/null 2>&1; then
            openssl rand -hex 16 > "${BRIDGE_TOKEN_FILE}"
        fi
        chmod 600 "${BRIDGE_TOKEN_FILE}"
        log "Wrote host agent token -> ${BRIDGE_TOKEN_FILE}"
    else
        log "Host agent token exists -> ${BRIDGE_TOKEN_FILE}"
    fi
    MCB_BRIDGE_PORT=52888
    if (echo > /dev/tcp/127.0.0.1/${MCB_BRIDGE_PORT}) >/dev/null 2>&1; then
        log "Bridge server already running on ${MCB_BRIDGE_PORT}. Killing server..."
        pkill -f "${SCRIPT_DIR}/tools/host_bridge.py" || true
    fi
    export MCB_BRIDGE_BIND=127.0.0.1
    nohup env MCB_BRIDGE_BIND="$MCB_BRIDGE_BIND" python3 "${SCRIPT_DIR}/tools/host_bridge.py" > "${SCRIPT_DIR}/mobilecybench_bridge.log" 2>&1 &
    log "Started mobilecybench host intermediary on port ${MCB_BRIDGE_PORT} (bind=${MCB_BRIDGE_BIND})"


    # notes on SDK versions
    echo ""
    echo -e "\033[33mNote: The default Android SDK version is $SDK_VERSION\033[0m"
    echo -e "\033[33mIf you need to use a different version of Android SDK, run: \033[0m"
    echo -e "\033[33m  ./setup.sh --sdk <sdk_version> --system-image google_apis\033[0m"
    # echo -e "\033[33mFor example, ./setup.sh --sdk 34 --system-image google_apis\033[0m"
    echo -e "\033[33mThis version should match your application's target device's API level.\033[0m"
}

# Run main function
main "$@"