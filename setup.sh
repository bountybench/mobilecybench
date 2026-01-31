#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="${SCRIPT_DIR}/setup.log"
ANDROID_HOME="${HOME}/.android-sdk"
EMULATOR_NAME="MobileCybenchEmu"

# Detect Python command using utility script
PYTHON=$("${SCRIPT_DIR}/utils/detect_python.sh") || exit 1

# Default SDK version and system image
DEFAULT_SDK_VERSION=35
DEFAULT_SYSTEM_IMAGE="google_apis"

# Load app metadata if app name provided
load_app_metadata() {
    local app_name="$1"
    local metadata_file="${SCRIPT_DIR}/apps/${app_name}/metadata.json"

    if [[ -f "$metadata_file" ]]; then
        # Convert path for Python on MinGW/Git Bash (Windows)
        if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "mingw"* ]]; then
            if command -v cygpath &>/dev/null; then
                metadata_file=$(cygpath -w "$metadata_file")
            fi
        fi

        local validation_result=$($PYTHON -c "
import json, sys
try:
    data = json.load(open(r'$metadata_file'))
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
    
    # Special handling for DeltaChat: force ARM architecture due to APK ABI requirements
    if [[ "$APP_NAME" == "deltachat-android" ]]; then
        echo "Note: DeltaChat requires ARM architecture emulator (APK built for arm64-v8a)"
        # Force ARM architecture by setting the build to use arm64 system image
        # This is done later in the detect_arch function override
    fi
    
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
                            metadata_path="$app_dir/metadata.json"
                            # Convert path for Python on MinGW/Git Bash (Windows)
                            if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "mingw"* ]]; then
                                if command -v cygpath &>/dev/null; then
                                    metadata_path=$(cygpath -w "$metadata_path")
                                fi
                            fi
                            app_sdk=$($PYTHON -c "import json; data=json.load(open(r'$metadata_path')); print(data.get('sdk', 'N/A'))" 2>/dev/null || echo "N/A")
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

# Check and install apktool
check_apktool() {
    log "Checking apktool installation..."

    if command_exists apktool; then
        local apktool_version=$(apktool --version 2>&1 | head -n1 || echo "unknown")
        log "apktool is already installed: $apktool_version"
        return 0
    fi

    log "apktool not found. Installing..."

    local os=$(detect_os)

    case "$os" in
        linux)
            log "Installing apktool via apt..."
            if command_exists apt-get; then
                sudo apt-get update && sudo apt-get install -y apktool
            elif command_exists apt; then
                sudo apt update && sudo apt install -y apktool
            else
                error_exit "Could not install apktool. Please install manually:
                sudo apt-get install apktool"
            fi
            ;;
        macos)
            log "Installing apktool via Homebrew..."
            if command_exists brew; then
                brew install apktool
            else
                error_exit "Homebrew not found. Please install Homebrew first:
                /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"
                Then run this setup script again."
            fi
            ;;
        windows)
            log "Windows detected. Please install apktool manually:"
            echo ""
            echo "Option 1 (Chocolatey - Recommended):"
            echo "  choco install apktool"
            echo ""
            echo "Option 2 (Manual):"
            echo "  1. Download from: https://github.com/iBotPeaches/Apktool/releases"
            echo "  2. Download both apktool.bat and apktool_X.X.X.jar"
            echo "  3. Rename the jar to apktool.jar"
            echo "  4. Place both files in C:\\Windows\\System32 or add to PATH"
            echo ""
            read -p "Press Enter after installing apktool to continue..."

            if ! command_exists apktool; then
                error_exit "apktool still not found. Please install it and try again."
            fi
            ;;
    esac

    # Verify installation
    if command_exists apktool; then
        local apktool_version=$(apktool --version 2>&1 | head -n1 || echo "unknown")
        log "apktool installed successfully: $apktool_version"
    else
        error_exit "Failed to install apktool"
    fi
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
    # Special case for DeltaChat: force ARM architecture due to APK ABI requirements
    if [[ "$APP_NAME" == "deltachat-android" ]]; then
        echo "arm64"
        return
    fi
    
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
    local system_image_google_apis=$(get_system_image "$arch" "google_apis")
    local system_image_playstore=$(get_system_image "$arch" "google_apis_playstore")

    log "Installing required Android packages for $arch architecture"
    log "SDK version: $SDK_VERSION"
    log "Installing BOTH system image types: google_apis and google_apis_playstore"
    log "This may take a few minutes if you are installing for the first time..."

    local sdkmanager="$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager"

    # Fix path for Windows MinGW users
    if [[ "$OSTYPE" == "msys" ]]; then
        {
            sdkmanager="$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager.bat"
        }
    fi

    # Accept licenses
    yes | "$sdkmanager" --licenses >/dev/null 2>&1 || true

    # Install essential packages including BOTH system images
    "$sdkmanager" \
        "platform-tools" \
        "emulator" \
        "platforms;android-${SDK_VERSION}" \
        "$system_image_google_apis" \
        "$system_image_playstore" \
        >/dev/null

    log "Android packages installed successfully (both google_apis and google_apis_playstore)"
}

# Create Android Virtual Device
create_avd() {
    local arch="$1"
    local system_image_google_apis=$(get_system_image "$arch" "google_apis")
    local system_image_playstore=$(get_system_image "$arch" "google_apis_playstore")

    log "Creating Android Virtual Devices for SDK $SDK_VERSION ($arch architecture)"
    log "Will create BOTH: google_apis (rootable) and google_apis_playstore (non-rootable)"

    local avdmanager="$ANDROID_HOME/cmdline-tools/latest/bin/avdmanager"

    # Fix path for Windows MinGW users
    if [[ "$OSTYPE" == "msys" ]]; then
        {
            avdmanager="$ANDROID_HOME/cmdline-tools/latest/bin/avdmanager.bat"
        }
    fi

    # Create google_apis AVD (rootable)
    local avd_name_google_apis="MobileCybenchEmulatorAPI${SDK_VERSION}_google_apis"
    log "Creating AVD: $avd_name_google_apis"
    echo "no" | "$avdmanager" create avd \
        -n "$avd_name_google_apis" \
        -k "$system_image_google_apis" \
        -d "pixel_2" \
        --force >/dev/null

    local avd_config="$HOME/.android/avd/${avd_name_google_apis}.avd/config.ini"
    if [[ -f "$avd_config" ]]; then
        {
            echo "hw.ramSize=4096"
            echo "hw.gpu.enabled=yes"
            echo "hw.gpu.mode=off"
            echo "hw.keyboard=yes"
            echo "showDeviceFrame=no"
            echo "skin.dynamic=yes"
        } >> "$avd_config"
    fi

    # Create google_apis_playstore AVD (non-rootable)
    local avd_name_playstore="MobileCybenchEmulatorAPI${SDK_VERSION}_google_apis_playstore"
    log "Creating AVD: $avd_name_playstore"
    echo "no" | "$avdmanager" create avd \
        -n "$avd_name_playstore" \
        -k "$system_image_playstore" \
        -d "pixel_2" \
        --force >/dev/null

    # Configure playstore AVD
    local avd_config_playstore="$HOME/.android/avd/${avd_name_playstore}.avd/config.ini"
    if [[ -f "$avd_config_playstore" ]]; then
        {
            echo "hw.ramSize=4096"
            echo "hw.gpu.enabled=yes"
            echo "hw.gpu.mode=off"
            echo "hw.keyboard=yes"
            echo "showDeviceFrame=no"
            echo "skin.dynamic=yes"
        } >> "$avd_config_playstore"
    fi

    log "Android Virtual Devices created successfully:"
    log "  - $avd_name_google_apis (rootable with 'adb root')"
    log "  - $avd_name_playstore (non-rootable, production-like)"
}

create_helper_scripts() {
    log "Creating helper scripts..."

    # Start emulator script - defaults to rootable (google_apis)
    cat > "${SCRIPT_DIR}/start_emulator.sh" << EOF
#!/bin/bash

ANDROID_HOME="\${HOME}/.android-sdk"
SDK_VERSION="${SDK_VERSION}"
SYSTEM_IMAGE="\${1:-google_apis}"  # Default to google_apis (rootable)

EMULATOR_NAME="MobileCybenchEmulatorAPI\${SDK_VERSION}_\${SYSTEM_IMAGE}"

# Check if AVD exists
if ! "\$ANDROID_HOME/emulator/emulator" -list-avds | grep -q "^\$EMULATOR_NAME\$"; then
    echo "Error: AVD '\$EMULATOR_NAME' not found"
    echo ""
    echo "Available AVDs:"
    "\$ANDROID_HOME/emulator/emulator" -list-avds
    echo ""
    echo "Usage: \$0 [google_apis|google_apis_playstore]"
    exit 1
fi

echo "Starting Android emulator: \$EMULATOR_NAME"
echo "This may take a few minutes on first boot..."

# Kill any existing emulators to prevent "more than one device" errors
if "\$ANDROID_HOME/platform-tools/adb" devices 2>/dev/null | grep -q "emulator"; then
    echo "Killing existing emulator(s)..."
    "\$ANDROID_HOME/platform-tools/adb" emu kill 2>/dev/null || true
    sleep 2
fi
pkill -f "emulator.*-avd" 2>/dev/null || true
sleep 1

# Remove stale lock files that can block startup after an unclean shutdown
find "\${HOME}/.android/avd/\${EMULATOR_NAME}.avd" -name "*.lock" -delete 2>/dev/null || true

"\$ANDROID_HOME/emulator/emulator" \\
    -avd "\$EMULATOR_NAME" \\
    -no-snapshot-save \\
    -wipe-data \\
    -gpu off \\
    -no-window \\
    -memory 4096 \\
    -no-audio \\
    -no-boot-anim \\
    &

echo "Emulator started in background"
echo "Waiting for device to be ready..."

# Start ADB server with -a flag to listen on all interfaces
# This allows Docker containers to connect via host.docker.internal:5037
echo "Starting ADB server (listening on all interfaces)..."
"\$ANDROID_HOME/platform-tools/adb" -a start-server

BOOT_TIMEOUT=300
START_TS=\$(date +%s)
echo "Waiting up to \${BOOT_TIMEOUT}s for device to appear..."
while true; do
    if "\$ANDROID_HOME/platform-tools/adb" devices 2>/dev/null | grep -qE "emulator-[0-9]+\s+device"; then
        echo "Device ready!"
        echo "To check device status: adb devices"
        exit 0
    fi
    ELAPSED=\$(( \$(date +%s) - START_TS ))
    if [ "\$ELAPSED" -ge "\$BOOT_TIMEOUT" ]; then
        echo "ERROR: Timed out after \${BOOT_TIMEOUT}s waiting for emulator device."
        echo "Emulator processes:"
        pgrep -f "emulator" || true
        echo "ADB devices:"
        "\$ANDROID_HOME/platform-tools/adb" devices 2>/dev/null || true
        exit 1
    fi
    printf '.'
    sleep 2
done
EOF

    # Stop emulator script
    cat > "${SCRIPT_DIR}/stop_emulator.sh" << 'EOF'
#!/bin/bash

echo "Stopping Android emulator..."
adb emu kill
echo "Emulator stopped"
EOF

    # Device check script
    cat > "${SCRIPT_DIR}/check_device.sh" << 'EOF'
#!/bin/bash

ANDROID_HOME="${HOME}/.android-sdk"

echo "Checking Android device status..."

if ! command -v adb >/dev/null 2>&1; then
    if [[ -f "$ANDROID_HOME/platform-tools/adb" ]]; then
        export PATH="$ANDROID_HOME/platform-tools:$PATH"
    else
        echo "ERROR: ADB not found. Please run setup.sh first."
        exit 1
    fi
fi

devices=$(adb devices | grep -v "List of devices" | grep -E "device$|emulator")

if [[ -z "$devices" ]]; then
    echo "No Android devices found."
    echo "Run ./start_emulator.sh or python emulator.py start to start the emulator."
    exit 1
fi

echo "Connected devices:"
echo "$devices"

device_id=$(echo "$devices" | head -n1 | awk '{print $1}')
echo "Testing device connectivity..."

if adb -s "$device_id" shell echo "test" >/dev/null 2>&1; then
    echo "Device is ready!"

    android_version=$(adb -s "$device_id" shell getprop ro.build.version.release)
    echo "Android version: $android_version"

    sdk_version=$(adb -s "$device_id" shell getprop ro.build.version.sdk)
    echo "SDK version (API level): $sdk_version"

    arch=$(adb -s "$device_id" shell getprop ro.product.cpu.abi)
    echo "Architecture: $arch"

    exit 0
else
    echo "Device connectivity test failed."
    exit 1
fi
EOF

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

    # Check and install apktool
    check_apktool
    
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
    echo "======================================================================"
    echo "                 Android Emulator Setup Complete!                    "
    echo "======================================================================"
    echo ""
    echo "Created AVDs:"
    echo "  1. MobileCybenchEmulatorAPI${SDK_VERSION}_google_apis"
    echo "     - Rootable with 'adb root' (for security testing)"
    echo ""
    echo "  2. MobileCybenchEmulatorAPI${SDK_VERSION}_google_apis_playstore"
    echo "     - Non-rootable (production-like environment)"
    echo ""
    if [[ "$APP_NAME" == "deltachat-android" ]]; then
        echo "  Note: ARM64 architecture (required for DeltaChat)"
    elif [[ "$arch" == "arm64" ]]; then
        echo "  Note: ARM64 architecture (Apple Silicon)"
    fi
    echo ""
    echo "Quick Start (Python CLI - Recommended):"
    echo "  python emulator.py start --sdk ${SDK_VERSION}                    # Start rootable emulator (default)"
    echo "  python emulator.py start --sdk ${SDK_VERSION} --no-rootable      # Start non-rootable emulator"
    echo "  python emulator.py list                                          # List available AVDs"
    echo "  python emulator.py stop                                          # Stop running emulator"
    echo ""
    echo "Or use bash scripts:"
    echo "  ./start_emulator.sh [google_apis|google_apis_playstore]          # Start emulator"
    echo "  ./check_device.sh                                                # Check device status"
    echo "  ./stop_emulator.sh                                               # Stop emulator"
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
    nohup env MCB_BRIDGE_BIND="$MCB_BRIDGE_BIND" $PYTHON "${SCRIPT_DIR}/tools/host_bridge.py" > "${SCRIPT_DIR}/mobilecybench_bridge.log" 2>&1 &
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