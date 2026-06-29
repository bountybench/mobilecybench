#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="${SCRIPT_DIR}/setup.log"

# If running within an experiment, redirect log to the experiment directory
if [[ -n "$MOBILECYBENCH_SESSION_ID" ]]; then
    EXP_LOG_DIR="${SCRIPT_DIR}/logs/experiment_${MOBILECYBENCH_SESSION_ID}"
    if [[ -d "$EXP_LOG_DIR" ]]; then
        LOG_FILE="${EXP_LOG_DIR}/setup.log"
    fi
fi

ANDROID_HOME="${HOME}/.android-sdk"

# Detect Python command using utility script
PYTHON=$("${SCRIPT_DIR}/utils/detect_python.sh") || exit 1

# Default SDK version and system image
DEFAULT_SDK_VERSION=35
DEFAULT_SYSTEM_IMAGE="google_apis"
SUPPORTED_SDK_VERSIONS=(33 34 35)

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

        # Non-interactive shells (CI, docker build, `bash setup.sh < /dev/null`)
        # default to "no" so the script never hangs waiting for input. Set
        # MOBILECYBENCH_NONINTERACTIVE=1 to force this behavior even on a tty,
        # or pass --yes-old-sdk on the command line to opt in unattended.
        if [[ -n "${MOBILECYBENCH_YES_OLD_SDK:-}" ]]; then
            echo "MOBILECYBENCH_YES_OLD_SDK is set — proceeding."
            return 0
        fi
        if [[ -n "${MOBILECYBENCH_NONINTERACTIVE:-}" ]] || ! [ -t 0 ]; then
            echo "Non-interactive shell detected; cancelling setup. Set"
            echo "MOBILECYBENCH_YES_OLD_SDK=1 to proceed unattended."
            exit 0
        fi

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
INIT_SUBMODULES="false"
INIT_SUBMODULE_APP=""

# Check if first argument is an app name (no dashes, exists in apps/ directory with valid metadata)
if [[ $# -gt 0 && "$1" != -* && -d "${SCRIPT_DIR}/apps/$1" ]]; then
    APP_NAME="$1"
    shift
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

    # Parse remaining flags (app mode)
    while [[ $# -gt 0 ]]; do
        case $1 in
            --init-submodules)
                if [[ -n "$2" && "$2" != -* ]]; then
                    INIT_SUBMODULE_APP="$2"
                    shift 2
                else
                    INIT_SUBMODULES="true"
                    shift
                fi
                ;;
            --init-submodules=*)
                INIT_SUBMODULE_APP="${1#*=}"
                shift
                ;;
            -h|--help)
                echo "Usage: $0 APP_NAME [--init-submodules [app_name]]"
                echo ""
                echo "Arguments:"
                echo "  APP_NAME                       App name from apps/ directory (uses SDK from metadata)"
                echo "  --init-submodules [app_name]   Initialize submodules (optionally only for one app)"
                exit 0
                ;;
            *)
                echo "Unknown option: $1"
                echo "Use -h or --help for usage information"
                exit 1
                ;;
        esac
    done
else
    # Standard flag parsing mode
    while [[ $# -gt 0 ]]; do
        case $1 in
            --init-submodules)
                if [[ -n "$2" && "$2" != -* ]]; then
                    INIT_SUBMODULE_APP="$2"
                    shift 2
                else
                    INIT_SUBMODULES="true"
                    shift
                fi
                ;;
            --init-submodules=*)
                INIT_SUBMODULE_APP="${1#*=}"
                shift
                ;;
            -h|--help)
                echo "Usage: $0"
                echo "   or: $0 APP_NAME"
                echo "   or: $0 [--init-submodules [app_name]]"
                echo ""
                echo "Mode 1: Use defaults (SDK $DEFAULT_SDK_VERSION, $DEFAULT_SYSTEM_IMAGE)"
                echo "Mode 2: Auto-configure from app metadata (Recommended)"
                echo ""
                echo "Arguments:"
                echo "  APP_NAME                       App name from apps/ directory (uses SDK from metadata)"
                echo "  --init-submodules [app_name]   Initialize submodules (optionally only for one app)"
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
                echo "  $0 moememos                           # Use moememos app (SDK 34, google_atd)"
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

# If app mode is used with --init-submodules (no app specified), default to that app
if [[ "$INIT_SUBMODULES" == "true" && -n "$APP_NAME" && -z "$INIT_SUBMODULE_APP" ]]; then
    INIT_SUBMODULE_APP="$APP_NAME"
fi

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Logging function that takes into account all supported SDK Versions
log_supported_sdks() {
    local label="${1:-SDK versions}"
    log "${label}: ${SUPPORTED_SDK_VERSIONS[*]}"
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

# Initialize git submodules (optional)
init_submodules() {
    if [[ "$INIT_SUBMODULES" != "true" && -z "$INIT_SUBMODULE_APP" ]]; then
        return 0
    fi

    if [[ ! -d "${SCRIPT_DIR}/.git" ]]; then
        log "Skipping submodules: not a git repository"
        return 0
    fi

    if ! command_exists git; then
        log "ERROR: git not found in PATH"
        return 1
    fi

    # TODO: switch submodule URLs to SSH instead of HTTPS
    if [[ -n "$INIT_SUBMODULE_APP" ]]; then
        if [[ ! -d "${SCRIPT_DIR}/apps/${INIT_SUBMODULE_APP}" ]]; then
            log "ERROR: App directory not found: apps/${INIT_SUBMODULE_APP}"
            return 1
        fi

        # Initialize every submodule registered under apps/<app>/ in .gitmodules.
        # Most apps have a single `codebase` submodule, but some (e.g. jitsi-meet)
        # ship additional infra submodules like `jitsi-docker` that must also
        # be initialized for start_runtime.sh to succeed.
        local app_prefix="apps/${INIT_SUBMODULE_APP}/"
        local submodule_paths=()
        while IFS= read -r submodule_path; do
            [[ -n "$submodule_path" ]] && submodule_paths+=("$submodule_path")
        done < <(
            git -C "$SCRIPT_DIR" config -f .gitmodules \
                --get-regexp '^submodule\..*\.path$' 2>/dev/null \
                | awk '{ print $2 }' \
                | grep "^${app_prefix}" || true
        )

        if [[ ${#submodule_paths[@]} -eq 0 ]]; then
            log "ERROR: No submodules registered under ${app_prefix} in .gitmodules"
            return 1
        fi

        for submodule_path in "${submodule_paths[@]}"; do
            log "Initializing submodule: ${submodule_path}"
            git -C "$SCRIPT_DIR" submodule update --init "$submodule_path"
            log "Submodule initialized: ${submodule_path}"
        done
    else
        # Initialize active app submodules only. Archived apps keep their
        # submodule metadata under archive/apps/ and can be initialized
        # explicitly by path when needed.
        log "Initializing active app submodules (recursive)..."
        local all_submodule_paths=()
        while IFS= read -r submodule_path; do
            [[ -n "$submodule_path" ]] && all_submodule_paths+=("$submodule_path")
        done < <(
            git -C "$SCRIPT_DIR" config -f .gitmodules \
                --get-regexp '^submodule\..*\.path$' 2>/dev/null \
                | awk '{ print $2 }' \
                | grep '^apps/' || true
        )

        for submodule_path in "${all_submodule_paths[@]}"; do
            git -C "$SCRIPT_DIR" submodule update --init --recursive "$submodule_path"
        done

        log "Active app submodules initialized."
        log "Note: zerodays/ is not required for probe_only mode. If you need redteam zero-day tasks and have access, run: git submodule update --init zerodays"
    fi
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

            # Non-interactive shells: fail loudly instead of hanging on input.
            # The Windows manual-install path can't be automated; the partner
            # has to install apktool themselves and re-run setup.sh.
            if [[ -n "${MOBILECYBENCH_NONINTERACTIVE:-}" ]] || ! [ -t 0 ]; then
                error_exit "apktool not installed and shell is non-interactive. \
Install apktool (see options above) and re-run setup.sh."
            fi

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

# Check and install the `zip` CLI. Required: templates/malicious_app/build_exploit_apk.sh
# shells out to `zip` to insert classes.dex into the unaligned APK envelope. `zip` is
# NOT part of the Android SDK (Ubuntu cloud images ship `unzip` but not `zip`), and
# without it the build aborts via the #1193 preflight guard — every malicious_app
# cell fails with MA artifact rejected: build_failed → results.status=exploit_invalid.
# The container/CI images already ship it; this keeps native host setups at parity.
check_zip() {
    log "Checking zip installation..."

    if command_exists zip; then
        log "zip is already installed: $(zip --version 2>&1 | head -n2 | tail -n1 || echo unknown)"
        return 0
    fi

    log "zip not found. Installing..."

    local os=$(detect_os)

    case "$os" in
        linux)
            if command_exists apt-get; then
                sudo apt-get update && sudo apt-get install -y zip
            elif command_exists apt; then
                sudo apt update && sudo apt install -y zip
            else
                error_exit "Could not install zip. Please install manually:
                sudo apt-get install -y zip"
            fi
            ;;
        macos)
            # macOS ships `zip` in /usr/bin by default; this branch is a safety net.
            if command_exists brew; then
                brew install zip
            else
                error_exit "Homebrew not found. Please install Homebrew first, then run setup again."
            fi
            ;;
        *)
            log "Please install the 'zip' CLI manually for your platform."
            return 0
            ;;
    esac

    if command_exists zip; then
        log "zip installed successfully: $(zip --version 2>&1 | head -n2 | tail -n1 || echo unknown)"
    else
        error_exit "Failed to install zip"
    fi
}

# Check and install the sqlcipher CLI. Required: several apps decrypt their
# SQLCipher-encrypted app DB via the `sqlcipher` binary during probing (e.g.
# apps/nextcloud-talk/probe_lib.py). The container/CI images already ship it;
# this keeps native host setups at parity so probes don't fail at runtime.
check_sqlcipher() {
    log "Checking sqlcipher installation..."

    if command_exists sqlcipher; then
        log "sqlcipher is already installed: $(sqlcipher --version 2>&1 | head -n1 || echo unknown)"
        return 0
    fi

    log "sqlcipher not found. Installing..."

    local os=$(detect_os)

    case "$os" in
        linux)
            if command_exists apt-get; then
                sudo apt-get update && sudo apt-get install -y sqlcipher
            elif command_exists apt; then
                sudo apt update && sudo apt install -y sqlcipher
            else
                error_exit "Could not install sqlcipher. Please install manually:
                sudo apt-get install -y sqlcipher"
            fi
            ;;
        macos)
            if command_exists brew; then
                brew install sqlcipher
            else
                error_exit "Homebrew not found. Please install Homebrew first, then run setup again."
            fi
            ;;
        *)
            log "Please install the 'sqlcipher' CLI manually for your platform."
            return 0
            ;;
    esac

    if command_exists sqlcipher; then
        log "sqlcipher installed successfully: $(sqlcipher --version 2>&1 | head -n1 || echo unknown)"
    else
        error_exit "Failed to install sqlcipher"
    fi
}

check_gh_auth() {
    if [[ -n "${MOBILECYBENCH_SKIP_GH_CHECK:-}" ]]; then
        log "Skipping gh auth check (MOBILECYBENCH_SKIP_GH_CHECK set)"
        return 0
    fi

    log "Checking GitHub CLI authentication..."

    if ! command_exists gh; then
        error_exit "GitHub CLI ('gh') not found. Required by default build_type='download-apk'.
  macOS:   brew install gh
  Linux:   sudo apt install gh   (or see https://cli.github.com/)
  Windows: choco install gh
Then run: gh auth login
(Building only from source / skip-apk? Set MOBILECYBENCH_SKIP_GH_CHECK=1 to skip this check.)"
    fi

    # Also accepts GH_TOKEN / GITHUB_TOKEN env auth (CI/Docker, no `gh auth login`).
    if ! gh auth status >/dev/null 2>&1; then
        error_exit "gh CLI installed but not authenticated. Run: gh auth login
(or set GH_TOKEN / GITHUB_TOKEN in your environment for non-interactive use)"
    fi

    log "gh CLI authenticated"
}

check_docker() {
    if [[ -n "${MOBILECYBENCH_SKIP_DOCKER_CHECK:-}" ]]; then
        log "Skipping docker check (MOBILECYBENCH_SKIP_DOCKER_CHECK set)"
        return 0
    fi

    log "Checking Docker + Compose v2..."

    if ! command_exists docker; then
        error_exit "Docker not found. Required for the agent stack and app backends.
  macOS/Windows: install Docker Desktop (bundles Compose).
  Linux:         sudo apt install docker.io docker-compose-v2
See https://docs.docker.com/engine/install/"
    fi

    if ! docker info >/dev/null 2>&1; then
        error_exit "Docker is installed but the daemon is not reachable.
Start Docker Desktop, or: sudo systemctl start docker
(and add your user to the docker group: sudo usermod -aG docker \$USER, then re-login)"
    fi

    # App backend + cleanup scripts call 'docker compose' (Compose v2 plugin).
    # 'apt install docker.io' does NOT bundle it; Docker Desktop does. Without
    # it every cell fails at cleanup.sh, so gate on it here rather than at runtime.
    if ! docker compose version >/dev/null 2>&1; then
        error_exit "Docker Compose v2 plugin not found ('docker compose'). App
backend/cleanup scripts require it.
  Linux:         sudo apt install docker-compose-v2
  macOS/Windows: included with Docker Desktop (update if missing)
See https://docs.docker.com/compose/install/"
    fi

    log "Docker + Compose v2 available"
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
    
    # Propagate session ID if present
    if [[ -n "$MOBILECYBENCH_SESSION_ID" ]]; then
        export MOBILECYBENCH_SESSION_ID="$MOBILECYBENCH_SESSION_ID"
    fi

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
    local sdk_v="$3"
    
    local arch_suffix
    if [[ "$arch" == "arm64" ]]; then
        arch_suffix="arm64-v8a"
    else
        arch_suffix="x86_64"
    fi
    
    echo "system-images;android-${sdk_v};${image_type};${arch_suffix}"
}

# Install required Android packages
install_android_packages() {
    local arch="$1"

    log "Installing required Android packages for $arch architecture"
    log_supported_sdks
    log "Installing system image type: google_apis"
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

    # Install essential packages using SDKManager for all supported versions.
    # build-tools is required by build_apk.sh (apksigner/zipalign) for the
    # malicious_app exploit-APK build; without it every MA cell fails with
    # build_failed. build_apk.sh picks the highest installed version.
    local packages=("platform-tools" "emulator" "build-tools;35.0.0")
    for sdk_v in "${SUPPORTED_SDK_VERSIONS[@]}"; do
        packages+=("platforms;android-${sdk_v}")
        packages+=("$(get_system_image "$arch" "google_apis" "$sdk_v")")
    done

    "$sdkmanager" "${packages[@]}" >/dev/null

    log "Android packages installed successfully (both google_apis)"
}

# Create Android Virtual Device
create_avd() {
    local arch="$1"

    log_supported_sdks "Creating Android Virtual Devices for SDK"
    log "Will create google_apis AVD for all SDK versions (rootable)"

    local avdmanager="$ANDROID_HOME/cmdline-tools/latest/bin/avdmanager"

    # Fix path for Windows MinGW users
    if [[ "$OSTYPE" == "msys" ]]; then
        {
            avdmanager="$ANDROID_HOME/cmdline-tools/latest/bin/avdmanager.bat"
        }
    fi

    for sdk_v in "${SUPPORTED_SDK_VERSIONS[@]}"; do
        local system_image
        system_image=$(get_system_image "$arch" "google_apis" "$sdk_v")
        local avd_name="MobileCybenchEmulatorAPI${sdk_v}_google_apis"
 
        log "Creating AVD: $avd_name"
        echo "no" | "$avdmanager" create avd \
            -n "$avd_name" \
            -k "$system_image" \
            -d "pixel_2" \
            --force >/dev/null
 
        local avd_config="$HOME/.android/avd/${avd_name}.avd/config.ini"
        if [[ -f "$avd_config" ]]; then
            {
                echo "hw.ramSize=2048"
                echo "hw.gpu.enabled=yes"
                echo "hw.gpu.mode=host"
                echo "hw.keyboard=yes"
                echo "showDeviceFrame=no"
                echo "skin.dynamic=yes"
            } >> "$avd_config"
        fi
 
        log "  - $avd_name created (rootable with 'adb root')"
    done
}

# Resolve which pip to install the project with. In order of preference:
#
#   1. The active venv (`$VIRTUAL_ENV/bin/pip`) — what the README path
#      yields and what subprocesses inheriting an activated PATH get.
#   2. `$PYTHON -m pip` — pairs with the python the rest of the script
#      uses, regardless of which `pip` happens to be earlier in PATH.
#
# Avoids:
#   - Bare `pip` resolving to a different python than `$PYTHON` when
#     the user has e.g. system pip on PATH ahead of a venv pip.
#   - Spurious PEP 668 failures on Homebrew macOS when the runner
#     subprocess inherits a non-activated PATH but $VIRTUAL_ENV is set.
install_self_package() {
    if [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/pip" ]]; then
        "${VIRTUAL_ENV}/bin/pip" install -e .
    else
        "$PYTHON" -m pip install -e .
    fi
}

# Main setup function
main() {
    install_self_package

    log "Starting Android Emulator Setup"
    log_supported_sdks "This script will install & prepare an emulator for the following Android SDK Versions"
    log "System image type: $SYSTEM_IMAGE_TYPE"
    
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

    # Check and install zip (MA artifact-packaging dependency, see #1193)
    check_zip

    # Check and install sqlcipher (probe-time app-DB decryption dependency)
    check_sqlcipher

    check_gh_auth

    # Check Docker engine + Compose v2 plugin (app backends + cleanup scripts)
    check_docker

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

    # Optional: initialize submodules
    init_submodules

    log "Setup completed successfully!"
    echo ""
    echo "======================================================================"
    echo "                 Android Emulator Setup Complete!                    "
    echo "======================================================================"
    echo ""
    echo "Created AVDs:"
    echo "  1. MobileCybenchEmulatorAPI33_google_apis"
    echo "     - Rootable with 'adb root' (for security testing)"
    echo "  2. MobileCybenchEmulatorAPI34_google_apis"
    echo "     - Rootable with 'adb root' (for security testing)"
    echo "  3. MobileCybenchEmulatorAPI35_google_apis"
    echo "     - Rootable with 'adb root' (for security testing)"
    echo ""
    echo ""
    if [[ "$APP_NAME" == "deltachat-android" ]]; then
        echo "  Note: ARM64 architecture (required for DeltaChat)"
    elif [[ "$arch" == "arm64" ]]; then
        echo "  Note: ARM64 architecture (Apple Silicon)"
    fi
    echo ""
    echo "Quick Start:"
    echo "  ./start_emulator.sh 33              # Start SDK 33 emulator (waits for boot)"
    echo "  ./start_emulator.sh 34              # Start SDK 34 emulator (waits for boot)"
    echo "  ./start_emulator.sh 35              # Start SDK 35 emulator (waits for boot)"
    echo "  ./check_device.sh                    # Check device status"
    echo "  ./stop_emulator.sh                   # Stop all emulators"
    echo ""
    echo "Note: You may need to restart your terminal or run:"
    echo "  source ~/.bashrc  (or ~/.zshrc)"
}

# Run main function
main "$@"
