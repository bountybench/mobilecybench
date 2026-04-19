#!/bin/bash
#
# APK Build Wrapper Script
#
# Unified build system that handles environment setup, building, signing,
# and output for all apps.
#
# Usage:
#   ./build_apk.sh <app_name> [--output <dir>] [--vuln <vuln_ref>] [--commit <ref>]
#   ./build_apk.sh <app_name> --hardened-patch <patch_path> [--commit <ref>]
#
# Examples:
#   ./build_apk.sh conversations
#     # Build the regular APK from the app's baseline commit
#   ./build_apk.sh conversations --output ./out
#     # Build to a custom output directory
#   ./build_apk.sh conversations --vuln vuln_0
#     # Build a vulnerable APK by applying vuln_0's vulnerability.patch
#     # (bare IDs are shorthand and must be unambiguous for the app)
#   ./build_apk.sh conversations --vuln synthetic_vulnerabilities/vuln_0
#     # Build a vulnerable APK from an explicit synthetic vulnerability bundle
#   ./build_apk.sh <app_name> --vuln zero_day_vulnerabilities/<bundle_name>
#     # Build a vulnerable APK from an explicit zero-day vulnerability bundle
#   ./build_apk.sh conversations --commit 60a32b1
#     # Build from an explicit commit instead of metadata.json commit_version
#   ./build_apk.sh conversations --hardened-patch /path/to/fix.patch
#     # Build a hardened APK from an explicit patch file (for example a task/report fix.patch)
#

set -e

# Color codes
GREEN="\033[1;32m"
RED="\033[1;31m"
YELLOW="\033[1;33m"
CYAN="\033[1;36m"
RESET="\033[0m"

# Message prefixes
INFO="${CYAN}[build_apk]${RESET}"
SUCCESS="${GREEN}[build_apk]${RESET}"
ERROR="${RED}[build_apk]${RESET}"
WARNING="${YELLOW}[build_apk]${RESET}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Variables
APP_NAME=""
VULN_ID=""
HARDENED_PATCH_PATH=""
OUTPUT_DIR=""
OUTPUT_DIR_EXPLICIT="0"
BUILD_COMMIT_OVERRIDE=""
HARDENED_OUTPUT_PATH=""

show_usage() {
    echo "Usage: $0 <app_name> [options]"
    echo ""
    echo "Arguments:"
    echo "  <app_name>          Name of the app to build (e.g., conversations, grocy)"
    echo ""
    echo "Options:"
    echo "  --output <dir>      Output directory for the APK (default: apps/<app_name>/apk/)"
    echo "  --vuln <vuln_ref>   Build a vulnerable APK by applying"
    echo "                      <resolved_vuln_dir>/vulnerability.patch"
    echo "                      <vuln_ref> may be a bare ID like vuln_0"
    echo "                      (only if unambiguous for the app), or an explicit path like"
    echo "                      synthetic_vulnerabilities/vuln_0 or"
    echo "                      zero_day_vulnerabilities/<bundle_name>"
    echo "  --commit <ref>      Override metadata.json commit_version for this build"
    echo "                      (useful for pinned historical/task baseline builds)"
    echo "  --hardened-patch <path>"
    echo "                      Build a hardened APK by applying an explicit patch file"
    echo "                      (useful when the remediation patch lives outside the app dir,"
    echo "                       e.g. a task/report fix.patch)"
    echo "  -h, --help          Show this help message"
    echo ""
    echo "Note: --vuln and --hardened-patch are mutually exclusive."
    echo ""
    echo "Examples:"
    echo "  $0 conversations"
    echo "    Build the regular APK from the app's baseline commit"
    echo "  $0 conversations --output ./artifacts"
    echo "    Build to a custom output directory"
    echo "  $0 conversations --vuln vuln_0"
    echo "    Build a vulnerable APK from vuln_0's vulnerability.patch"
    echo "  $0 conversations --vuln synthetic_vulnerabilities/vuln_0"
    echo "    Build a vulnerable APK from an explicit synthetic vulnerability bundle"
    echo "  $0 <app_name> --vuln zero_day_vulnerabilities/<bundle_name>"
    echo "    Build a vulnerable APK from an explicit zero-day vulnerability bundle"
    echo "  $0 conversations --commit 60a32b1"
    echo "    Build from an explicit commit"
    echo "  $0 conversations --hardened-patch /path/to/fix.patch"
    echo "    Build a hardened APK from an explicit patch file"
    echo ""
    echo "Output naming:"
    echo "  Regular build:    apk/<app_name>.apk"
    echo "  Vuln build:       apk/<basename(vuln_ref)>/<app_name>.apk"
    echo "  Hardened build:   zerodays/reports/<app>/<report>/artifacts/hardened_apk/<app_name>.apk"
    echo "                    (for task fix.patch paths)"
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --vuln)
            if [ -z "$2" ] || [[ "$2" == -* ]]; then
                echo -e "${ERROR} --vuln requires a vulnerability reference argument (e.g., vuln_0)"
                show_usage
                exit 1
            fi
            VULN_ID="$2"
            shift 2
            ;;
        --hardened-patch)
            if [ -z "$2" ] || [[ "$2" == -* ]]; then
                echo -e "${ERROR} --hardened-patch requires a patch file path"
                show_usage
                exit 1
            fi
            HARDENED_PATCH_PATH="$2"
            shift 2
            ;;
        --output)
            if [ -z "$2" ] || [[ "$2" == -* ]]; then
                echo -e "${ERROR} --output requires a directory path"
                show_usage
                exit 1
            fi
            OUTPUT_DIR="$2"
            OUTPUT_DIR_EXPLICIT="1"
            shift 2
            ;;
        --commit)
            if [ -z "$2" ] || [[ "$2" == -* ]]; then
                echo -e "${ERROR} --commit requires a git ref or commit"
                show_usage
                exit 1
            fi
            BUILD_COMMIT_OVERRIDE="$2"
            shift 2
            ;;
        -h|--help)
            show_usage
            exit 0
            ;;
        -*)
            echo -e "${ERROR} Unknown option: $1"
            show_usage
            exit 1
            ;;
        *)
            if [ -z "$APP_NAME" ]; then
                APP_NAME="$1"
            else
                echo -e "${ERROR} Multiple app names specified. Only one app allowed."
                show_usage
                exit 1
            fi
            shift
            ;;
    esac
done

# Validate app name provided
if [ -z "$APP_NAME" ]; then
    echo -e "${ERROR} App name is required"
    show_usage
    exit 1
fi

# Resolve app directory
APP_DIR="$ROOT_DIR/apps/$APP_NAME"
if [ ! -d "$APP_DIR" ]; then
    echo -e "${ERROR} App directory not found: $APP_DIR"
    exit 1
fi

# Set default output directory
if [ -z "$OUTPUT_DIR" ]; then
    OUTPUT_DIR="$APP_DIR/apk"
fi

VULN_OUTPUT_NAME=""
if [ -n "$VULN_ID" ]; then
    VULN_OUTPUT_NAME="$(basename "$VULN_ID")"
fi

# Validate build script exists
if [ ! -f "$APP_DIR/build.sh" ]; then
    echo -e "${ERROR} build.sh not found in $APP_DIR"
    exit 1
fi

resolve_vuln_dir() {
    local vuln_id="$1"
    local synthetic_dir="$APP_DIR/synthetic_vulnerabilities/$vuln_id"
    local zero_day_dir="$APP_DIR/zero_day_vulnerabilities/$vuln_id"

    if [[ "$vuln_id" == */* ]]; then
        local explicit_dir="$APP_DIR/$vuln_id"
        if [ -d "$explicit_dir" ]; then
            printf '%s\n' "$explicit_dir"
            return 0
        fi
        if [ -d "$vuln_id" ]; then
            printf '%s\n' "$vuln_id"
            return 0
        fi
        return 1
    fi

    if [ -d "$synthetic_dir" ] && [ -d "$zero_day_dir" ]; then
        echo -e "${ERROR} Ambiguous vulnerability ID '$vuln_id' for $APP_NAME" >&2
        echo -e "${ERROR} Both directories exist:" >&2
        echo -e "${ERROR}   $synthetic_dir" >&2
        echo -e "${ERROR}   $zero_day_dir" >&2
        echo -e "${ERROR} Re-run with an explicit path, for example:" >&2
        echo -e "${ERROR}   --vuln synthetic_vulnerabilities/$vuln_id" >&2
        echo -e "${ERROR}   --vuln zero_day_vulnerabilities/$vuln_id" >&2
        return 1
    fi

    if [ -d "$synthetic_dir" ]; then
        printf '%s\n' "$synthetic_dir"
        return 0
    fi

    if [ -d "$zero_day_dir" ]; then
        printf '%s\n' "$zero_day_dir"
        return 0
    fi

    return 1
}

# Check codebase submodule is initialized
check_submodule_initialized() {
    local codebase_dir="$APP_DIR/codebase"

    if [ ! -d "$codebase_dir" ]; then
        echo -e "${ERROR} Codebase directory not found: $codebase_dir"
        echo -e "${ERROR} Please initialize the submodule: git submodule update --init apps/$APP_NAME/codebase"
        return 1
    fi

    # Check if submodule is initialized (has files)
    if [ -z "$(ls -A "$codebase_dir" 2>/dev/null)" ]; then
        echo -e "${ERROR} Codebase submodule is not initialized (directory is empty)"
        echo -e "${ERROR} Please initialize the submodule: git submodule update --init apps/$APP_NAME/codebase"
        return 1
    fi

    echo -e "${INFO} Codebase submodule is initialized"
    return 0
}

# Setup Java environment based on version from metadata.json
setup_java() {
    local java_version
    java_version=$(jq -r '.java // "17"' "$APP_DIR/metadata.json")

    echo -e "${INFO} Setting up Java $java_version..."

    # Try common Java installation paths
    if [[ -d "/opt/homebrew/opt/openjdk@${java_version}" ]]; then
        export JAVA_HOME="/opt/homebrew/opt/openjdk@${java_version}/libexec/openjdk.jdk/Contents/Home"
    elif [[ -d "/usr/lib/jvm/java-${java_version}-openjdk" ]]; then
        export JAVA_HOME="/usr/lib/jvm/java-${java_version}-openjdk"
    elif [[ -d "/usr/lib/jvm/java-${java_version}-openjdk-amd64" ]]; then
        export JAVA_HOME="/usr/lib/jvm/java-${java_version}-openjdk-amd64"
    elif command -v /usr/libexec/java_home &>/dev/null; then
        export JAVA_HOME="$(/usr/libexec/java_home -v "$java_version" 2>/dev/null || true)"
    fi

    # Fallback to system Java
    if [[ -z "$JAVA_HOME" || ! -d "$JAVA_HOME" ]]; then
        export JAVA_HOME=$(java -XshowSettings:properties -version 2>&1 | grep 'java.home' | awk '{print $3}')
    fi

    if [[ -z "$JAVA_HOME" || ! -d "$JAVA_HOME" ]]; then
        echo -e "${ERROR} Could not find Java $java_version"
        return 1
    fi

    export PATH="$JAVA_HOME/bin:$PATH"
    echo -e "${INFO} JAVA_HOME=$JAVA_HOME"
}

# Setup Android SDK environment
setup_android() {
    echo -e "${INFO} Setting up Android SDK..."

    # Try common Android SDK paths
    if [[ -n "$ANDROID_HOME" && -d "$ANDROID_HOME" ]]; then
        : # Already set
    elif [[ -d "$HOME/.android-sdk" ]]; then
        export ANDROID_HOME="$HOME/.android-sdk"
    elif [[ -d "/usr/local/lib/android/sdk" ]]; then
        export ANDROID_HOME="/usr/local/lib/android/sdk"
    elif [[ -d "$HOME/Android/Sdk" ]]; then
        export ANDROID_HOME="$HOME/Android/Sdk"
    else
        echo -e "${ERROR} Android SDK not found"
        return 1
    fi

    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
    echo -e "${INFO} ANDROID_HOME=$ANDROID_HOME"

    # Create local.properties for gradle
    echo "sdk.dir=$ANDROID_HOME" > "$APP_DIR/codebase/local.properties"
}

# Standard location for unsigned APK (build.sh copies here)
UNSIGNED_APK="$APP_DIR/unsigned.apk"

# Clean up temporary files
cleanup_unsigned_apk() {
    if [[ -f "$UNSIGNED_APK" ]]; then
        rm -f "$UNSIGNED_APK"
    fi
}

# Ensure cleanup on exit
trap cleanup_unsigned_apk EXIT

# Sign APK using shared keystore
sign_apk() {
    local unsigned_apk="$1"
    local output_apk="$2"

    echo -e "${INFO} Signing APK..."

    local keystore="$ROOT_DIR/utils/benchmark.keystore"
    local keystore_pass="password"
    local key_alias="benchmark-key"

    # Create keystore if it doesn't exist
    if [[ ! -f "$keystore" ]]; then
        echo -e "${INFO} Creating signing keystore..."
        keytool -genkey -v -keystore "$keystore" \
            -alias "$key_alias" -keyalg RSA -keysize 2048 \
            -validity 10000 -storepass "$keystore_pass" -keypass "$keystore_pass" \
            -dname "CN=MobileCyBench, OU=Test, O=Test, L=Test, S=Test, C=US"
    fi

    # Find apksigner
    local apksigner=""
    if [[ -d "$ANDROID_HOME/build-tools" ]]; then
        apksigner=$(find "$ANDROID_HOME/build-tools" -name "apksigner" -type f 2>/dev/null | sort -V | tail -1)
    fi

    if [[ -z "$apksigner" ]]; then
        echo -e "${ERROR} apksigner not found in ANDROID_HOME/build-tools"
        return 1
    fi

    # Sign the APK (disable v4 signing to avoid .idsig files)
    "$apksigner" sign \
        --ks "$keystore" \
        --ks-key-alias "$key_alias" \
        --ks-pass "pass:$keystore_pass" \
        --key-pass "pass:$keystore_pass" \
        --v4-signing-enabled false \
        --out "$output_apk" \
        "$unsigned_apk"

    echo -e "${SUCCESS} APK signed: $output_apk"
}

# Checkout the commit specified in metadata.json, unless an explicit
# --commit override was provided.
checkout_commit() {
    if [ -n "$BUILD_COMMIT_OVERRIDE" ]; then
        echo -e "${INFO} Checking out explicit build commit override..."
    else
        echo -e "${INFO} Checking out commit from metadata.json..."
    fi

    local metadata_file="$APP_DIR/metadata.json"
    if [ ! -f "$metadata_file" ]; then
        echo -e "${ERROR} metadata.json not found in $APP_DIR"
        return 1
    fi

    local commit=""
    if [ -n "$BUILD_COMMIT_OVERRIDE" ]; then
        commit="$BUILD_COMMIT_OVERRIDE"
    else
        commit=$(jq -r '.commit_version // empty' "$metadata_file")
    fi

    if [ -z "$commit" ]; then
        echo -e "${ERROR} No build commit could be resolved"
        return 1
    fi

    echo -e "${INFO} Target commit: $commit"

    cd "$APP_DIR/codebase"

    # Clean the codebase (including nested submodules)
    echo -e "${INFO} Cleaning codebase..."
    git reset --hard HEAD
    git clean -fdx
    git submodule foreach --recursive git reset --hard HEAD 2>/dev/null || true
    git submodule foreach --recursive git clean -fdx 2>/dev/null || true

    # Checkout the commit
    git checkout "$commit"
    git submodule update --init --recursive 2>/dev/null || true

    cd "$ROOT_DIR"
    echo -e "${SUCCESS} Checked out commit: $commit"
}

# Apply a patch file to the codebase
apply_patch() {
    local patch_file="$1"
    local patch_name="$2"

    echo -e "${INFO} Applying $patch_name: $patch_file"

    if [ ! -f "$patch_file" ]; then
        echo -e "${ERROR} Patch not found: $patch_file"
        return 1
    fi

    cd "$APP_DIR/codebase"

    # Validate patch can be applied
    if ! git apply --check "$patch_file" 2>&1; then
        echo -e "${ERROR} Patch validation failed - $patch_name cannot be applied cleanly"
        cd "$ROOT_DIR"
        return 1
    fi

    # Apply the patch
    if ! git apply "$patch_file"; then
        echo -e "${ERROR} Failed to apply $patch_name"
        cd "$ROOT_DIR"
        return 1
    fi

    cd "$ROOT_DIR"
    echo -e "${SUCCESS} $patch_name applied successfully"
    return 0
}

# Apply vulnerability patch for synthetic vuln builds
apply_vulnerability_patch() {
    local vuln_id="$1"
    local vuln_dir
    vuln_dir="$(resolve_vuln_dir "$vuln_id")" || {
        echo -e "${ERROR} Vulnerability directory not found for $vuln_id"
        return 1
    }
    local patch_file="$vuln_dir/vulnerability.patch"
    apply_patch "$patch_file" "vulnerability.patch"
}

# Run the per-app build script
run_build() {
    echo -e "${INFO} Running build script..."

    cd "$APP_DIR"
    chmod +x build.sh
    if ! ./build.sh; then
        echo -e "${ERROR} build.sh failed"
        cd "$ROOT_DIR"
        return 1
    fi

    cd "$ROOT_DIR"
    echo -e "${SUCCESS} Build completed"
    return 0
}

# Build, sign, and copy APK to output
build_and_package() {
    # Setup environment
    setup_java || return 1
    setup_android || return 1

    # Setup unified keystore for apps that need signing during gradle build
    local keystore="$ROOT_DIR/utils/benchmark.keystore"
    local keystore_pass="password"
    local key_alias="benchmark-key"

    # Create keystore if it doesn't exist (needed before gradle build, not just signing)
    if [[ ! -f "$keystore" ]]; then
        echo -e "${INFO} Creating signing keystore..."
        keytool -genkey -v -keystore "$keystore" \
            -alias "$key_alias" -keyalg RSA -keysize 2048 \
            -validity 10000 -storepass "$keystore_pass" -keypass "$keystore_pass" \
            -dname "CN=MobileCyBench, OU=Test, O=Test, L=Test, S=Test, C=US"
    fi

    # Disable Gradle build cache for patched builds to prevent stale cached
    # compilation outputs from a prior clean build being reused.
    if [[ -n "$VULN_ID" || -n "$HARDENED_PATCH_PATH" ]]; then
        export GRADLE_EXTRA_ARGS="--no-build-cache"
    else
        export GRADLE_EXTRA_ARGS=""
    fi

    # Export env vars - single source of truth for all apps
    export KEYSTORE_PATH="$keystore"
    export KEYSTORE_PASSWORD="$keystore_pass"
    export KEYSTORE_ALIAS="$key_alias"
    export KEYSTORE_ALIAS_PASSWORD="$keystore_pass"
    # Alternative env var names used by some apps
    export ANDROID_KEYSTORE="$keystore"
    export ANDROID_KEYSTORE_PASSWORD="$keystore_pass"
    export ANDROID_KEY_ALIAS="$key_alias"
    export ANDROID_KEY_PASSWORD="$keystore_pass"

    # Clean up any leftover unsigned APK
    cleanup_unsigned_apk

    # Run the build
    if ! run_build; then
        cleanup_unsigned_apk
        return 1
    fi

    # Check for unsigned APK (build.sh should have copied it here)
    if [[ ! -f "$UNSIGNED_APK" ]]; then
        echo -e "${ERROR} build.sh did not produce $UNSIGNED_APK"
        echo -e "${ERROR} Each build.sh must copy its APK to: \$SCRIPT_DIR/unsigned.apk"
        return 1
    fi

    echo -e "${INFO} Found unsigned APK: $UNSIGNED_APK"

    # Determine output path (vuln/hardened builds go in subdirectory)
    local output_path
    if [[ -n "$VULN_ID" ]]; then
        mkdir -p "$OUTPUT_DIR/$VULN_OUTPUT_NAME"
        output_path="$OUTPUT_DIR/$VULN_OUTPUT_NAME/${APP_NAME}.apk"
    elif [[ -n "$HARDENED_PATCH_PATH" ]]; then
        mkdir -p "$(dirname "$HARDENED_OUTPUT_PATH")"
        output_path="$HARDENED_OUTPUT_PATH"
    else
        mkdir -p "$OUTPUT_DIR"
        output_path="$OUTPUT_DIR/${APP_NAME}.apk"
    fi

    # Sign and copy
    if ! sign_apk "$UNSIGNED_APK" "$output_path"; then
        cleanup_unsigned_apk
        return 1
    fi

    # Clean up unsigned APK
    cleanup_unsigned_apk

    echo -e "${SUCCESS} Output: $output_path"
    return 0
}

# Main logic
main() {
    echo -e "${INFO} =================================="
    echo -e "${INFO} APK Build Wrapper"
    echo -e "${INFO} =================================="
    echo -e "${INFO} App: $APP_NAME"
    if [ -n "$BUILD_COMMIT_OVERRIDE" ]; then
        echo -e "${INFO} Commit override: $BUILD_COMMIT_OVERRIDE"
    fi

    # Validate mutually exclusive flags
    local mode_count=0
    [[ -n "$VULN_ID" ]] && mode_count=$((mode_count + 1))
    [[ -n "$HARDENED_PATCH_PATH" ]] && mode_count=$((mode_count + 1))
    if [ "$mode_count" -gt 1 ]; then
        echo -e "${ERROR} --vuln and --hardened-patch are mutually exclusive"
        exit 1
    fi

    if [ -n "$VULN_ID" ]; then
        echo -e "${INFO} Output: $OUTPUT_DIR/$VULN_OUTPUT_NAME/${APP_NAME}.apk"
        echo -e "${INFO} Mode: Vulnerable APK build ($VULN_ID)"

        # Validate vulnerability directory exists
        local vuln_dir
        vuln_dir="$(resolve_vuln_dir "$VULN_ID")" || {
            echo -e "${ERROR} Vulnerability directory not found or ambiguous for: $VULN_ID"
            exit 1
        }

        if [ ! -f "$vuln_dir/vulnerability.patch" ]; then
            echo -e "${ERROR} vulnerability.patch not found in $vuln_dir"
            exit 1
        fi
    elif [ -n "$HARDENED_PATCH_PATH" ]; then
        # Resolve to absolute path
        if [[ "$HARDENED_PATCH_PATH" != /* ]]; then
            HARDENED_PATCH_PATH="$(cd "$(dirname "$HARDENED_PATCH_PATH")" && pwd)/$(basename "$HARDENED_PATCH_PATH")"
        fi

        if [ ! -f "$HARDENED_PATCH_PATH" ]; then
            echo -e "${ERROR} Patch file not found: $HARDENED_PATCH_PATH"
            exit 1
        fi

        if [ "$OUTPUT_DIR_EXPLICIT" = "1" ]; then
            HARDENED_OUTPUT_PATH="$OUTPUT_DIR/${APP_NAME}.apk"
        elif [[ "$HARDENED_PATCH_PATH" =~ (.*/reports/${APP_NAME}/[^/]+)/ ]]; then
            HARDENED_OUTPUT_PATH="${BASH_REMATCH[1]}/artifacts/hardened_apk/${APP_NAME}.apk"
        else
            echo -e "${ERROR} Could not resolve hardened APK output path from patch: $HARDENED_PATCH_PATH"
            echo -e "${ERROR} Use a task fix.patch under zerodays/reports/<app>/<report>/ or pass --output <dir>"
            exit 1
        fi

        echo -e "${INFO} Output: $HARDENED_OUTPUT_PATH"
        echo -e "${INFO} Mode: Hardened APK build (explicit patch)"
        echo -e "${INFO} Patch: $HARDENED_PATCH_PATH"
    else
        echo -e "${INFO} Output: $OUTPUT_DIR/${APP_NAME}.apk"
        echo -e "${INFO} Mode: Regular APK build"
    fi

    echo -e "${INFO} =================================="

    # Step 1: Check submodule is initialized
    check_submodule_initialized || exit 1

    # Step 2: Checkout the correct commit
    checkout_commit || exit 1

    if [ -n "$VULN_ID" ]; then
        # Building vulnerable APK from the declared vulnerable baseline.

        # Step 3: Apply vulnerability patch
        if ! apply_vulnerability_patch "$VULN_ID"; then
            echo -e "${ERROR} Failed to apply vulnerability patch"
            checkout_commit || true
            exit 1
        fi

        # Step 4: Build, sign, and package
        if ! build_and_package; then
            echo -e "${ERROR} Build failed"
            checkout_commit || true
            exit 1
        fi

        # Step 5: Restore clean codebase state
        echo -e "${INFO} Restoring clean codebase state..."
        checkout_commit || true

        echo -e "${SUCCESS} =================================="
        echo -e "${SUCCESS} Vulnerable APK build completed!"
        echo -e "${SUCCESS} Output: $OUTPUT_DIR/$VULN_OUTPUT_NAME/${APP_NAME}.apk"
        echo -e "${SUCCESS} =================================="
    elif [ -n "$HARDENED_PATCH_PATH" ]; then
        # Hardened build with explicit patch file

        # Step 3: Apply the provided patch
        if ! apply_patch "$HARDENED_PATCH_PATH" "hardened patch"; then
            echo -e "${ERROR} Failed to apply hardened patch"
            checkout_commit || true
            exit 1
        fi

        # Step 4: Build, sign, and package
        if ! build_and_package; then
            echo -e "${ERROR} Build failed"
            checkout_commit || true
            exit 1
        fi

        # Step 5: Restore clean codebase state
        echo -e "${INFO} Restoring clean codebase state..."
        checkout_commit || true

        echo -e "${SUCCESS} =================================="
        echo -e "${SUCCESS} Hardened APK build completed!"
        echo -e "${SUCCESS} Output: $HARDENED_OUTPUT_PATH"
        echo -e "${SUCCESS} =================================="
    else
        # Regular (original) build — NO patches applied

        # Step 3: Build, sign, and package
        if ! build_and_package; then
            checkout_commit || true
            exit 1
        fi

        # Step 4: Restore clean codebase state
        echo -e "${INFO} Restoring clean codebase state..."
        checkout_commit || true

        echo -e "${SUCCESS} =================================="
        echo -e "${SUCCESS} APK build completed!"
        echo -e "${SUCCESS} Output: $OUTPUT_DIR/${APP_NAME}.apk"
        echo -e "${SUCCESS} =================================="
    fi
}

# Run main
main "$@"
