#!/bin/bash
#
# APK Build Wrapper Script
#
# This script wraps setup_app_source.sh to provide a unified interface for building
# APKs for both regular and synthetic vulnerability scenarios.
#
# Usage:
#   ./build_apk.sh <app_name> [--vuln <vuln_id>]
#
# Examples:
#   ./build_apk.sh conversations                    # Build regular APK
#   ./build_apk.sh conversations --vuln vuln_0      # Build APK with vuln_0 patch applied
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

show_usage() {
    echo "Usage: $0 <app_name> [options]"
    echo ""
    echo "Arguments:"
    echo "  <app_name>          Name of the app to build (e.g., conversations, joplin)"
    echo ""
    echo "Options:"
    echo "  --vuln <vuln_id>    Build APK with synthetic vulnerability patch applied"
    echo "                      (e.g., vuln_0, vuln_1)"
    echo "  -h, --help          Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 conversations                    # Build regular APK"
    echo "  $0 conversations --vuln vuln_0      # Build APK with vuln_0 patch"
    echo ""
    echo "Output locations:"
    echo "  Regular build:  apps/<app_name>/apk/<apk_files>"
    echo "  Vuln build:     apps/<app_name>/apk/<vuln_id>/<apk_files>"
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --vuln)
            if [ -z "$2" ] || [[ "$2" == -* ]]; then
                echo -e "${ERROR} --vuln requires a vulnerability ID argument (e.g., vuln_0)"
                show_usage
                exit 1
            fi
            VULN_ID="$2"
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

# Validate setup_app_source.sh exists
if [ ! -f "$APP_DIR/setup_app_source.sh" ]; then
    echo -e "${ERROR} setup_app_source.sh not found in $APP_DIR"
    echo -e "${ERROR} This script requires setup_app_source.sh to build APKs from source"
    exit 1
fi

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

# Checkout the commit specified in metadata.json
checkout_commit() {
    echo -e "${INFO} Checking out commit from metadata.json..."

    local metadata_file="$APP_DIR/metadata.json"
    if [ ! -f "$metadata_file" ]; then
        echo -e "${ERROR} metadata.json not found in $APP_DIR"
        return 1
    fi

    local commit
    commit=$(jq -r '.commit_version // empty' "$metadata_file")

    if [ -z "$commit" ]; then
        echo -e "${ERROR} No commit_version found in metadata.json"
        return 1
    fi

    echo -e "${INFO} Target commit: $commit"

    cd "$APP_DIR/codebase"

    # Clean the codebase
    echo -e "${INFO} Cleaning codebase..."
    git reset --hard HEAD
    git clean -fdx

    # Checkout the commit
    git checkout "$commit"

    cd "$ROOT_DIR"
    echo -e "${SUCCESS} Checked out commit: $commit"
}

# Apply vulnerability patch
apply_vulnerability_patch() {
    local vuln_id="$1"
    local patch_file="$APP_DIR/synthetic_vulnerabilities/$vuln_id/vulnerability.patch"

    echo -e "${INFO} Applying vulnerability patch: $patch_file"

    if [ ! -f "$patch_file" ]; then
        echo -e "${ERROR} Vulnerability patch not found: $patch_file"
        return 1
    fi

    cd "$APP_DIR/codebase"

    # Validate patch can be applied (--allow-empty for vulns that exist in codebase)
    if ! git apply --check --allow-empty "$patch_file" 2>&1; then
        echo -e "${ERROR} Patch validation failed - patch cannot be applied cleanly"
        cd "$ROOT_DIR"
        return 1
    fi

    # Apply the patch
    if ! git apply --allow-empty "$patch_file"; then
        echo -e "${ERROR} Failed to apply patch"
        cd "$ROOT_DIR"
        return 1
    fi

    cd "$ROOT_DIR"
    echo -e "${SUCCESS} Vulnerability patch applied successfully"
    return 0
}

# Backup existing APKs to temporary location
backup_existing_apks() {
    local apk_dir="$APP_DIR/apk"
    local backup_dir

    if [ ! -d "$apk_dir" ]; then
        echo -e "${INFO} No existing APK directory - nothing to backup"
        return 0
    fi

    # Check if there are any APK files to backup (excluding vuln_* subdirectories)
    local apk_count
    apk_count=$(find "$apk_dir" -maxdepth 1 -name "*.apk" -type f 2>/dev/null | wc -l)

    if [ "$apk_count" -eq 0 ]; then
        echo -e "${INFO} No existing APKs in $apk_dir - nothing to backup"
        return 0
    fi

    # Create temporary backup directory
    backup_dir=$(mktemp -d "${TMPDIR:-/tmp}/apk_backup_${APP_NAME}_XXXXXX")

    echo -e "${INFO} Backing up $apk_count existing APK(s) to: $backup_dir"

    # Move APKs to backup (not copy!) to ensure setup_app_source.sh rebuilds
    # Some apps (simplelogin, wallabag, tindroid) skip building if APK exists
    find "$apk_dir" -maxdepth 1 -name "*.apk" -type f -exec mv {} "$backup_dir/" \;

    # Store backup path for later restoration
    echo "$backup_dir" > "$APP_DIR/.apk_backup_path"

    echo -e "${SUCCESS} APKs backed up (moved) successfully"
    return 0
}

# Restore backed up APKs
restore_backed_up_apks() {
    local backup_path_file="$APP_DIR/.apk_backup_path"
    local apk_dir="$APP_DIR/apk"

    if [ ! -f "$backup_path_file" ]; then
        echo -e "${INFO} No backup to restore"
        return 0
    fi

    local backup_dir
    backup_dir=$(cat "$backup_path_file")

    if [ ! -d "$backup_dir" ]; then
        echo -e "${WARNING} Backup directory no longer exists: $backup_dir"
        rm -f "$backup_path_file"
        return 0
    fi

    # Count APKs in backup
    local apk_count
    apk_count=$(find "$backup_dir" -maxdepth 1 -name "*.apk" -type f 2>/dev/null | wc -l)

    if [ "$apk_count" -eq 0 ]; then
        echo -e "${INFO} No APKs in backup directory"
        rm -rf "$backup_dir"
        rm -f "$backup_path_file"
        return 0
    fi

    echo -e "${INFO} Restoring $apk_count APK(s) from backup..."

    # Ensure apk directory exists
    mkdir -p "$apk_dir"

    # Restore APKs
    cp "$backup_dir"/*.apk "$apk_dir/"

    # Clean up backup
    rm -rf "$backup_dir"
    rm -f "$backup_path_file"

    echo -e "${SUCCESS} Original APKs restored"
    return 0
}

# Move built APKs to vuln directory
move_apks_to_vuln_dir() {
    local vuln_id="$1"
    local apk_dir="$APP_DIR/apk"
    local vuln_apk_dir="$apk_dir/$vuln_id"

    if [ ! -d "$apk_dir" ]; then
        echo -e "${ERROR} APK directory not found after build: $apk_dir"
        return 1
    fi

    # Find APKs at top level (not in subdirectories)
    local apk_count
    apk_count=$(find "$apk_dir" -maxdepth 1 -name "*.apk" -type f 2>/dev/null | wc -l)

    if [ "$apk_count" -eq 0 ]; then
        echo -e "${ERROR} No APKs found in $apk_dir after build"
        return 1
    fi

    # Create vuln APK directory (overwrite if exists)
    rm -rf "$vuln_apk_dir"
    mkdir -p "$vuln_apk_dir"

    echo -e "${INFO} Moving $apk_count APK(s) to: $vuln_apk_dir"

    # Move APKs to vuln directory
    find "$apk_dir" -maxdepth 1 -name "*.apk" -type f -exec mv {} "$vuln_apk_dir/" \;

    echo -e "${SUCCESS} APKs moved to $vuln_apk_dir"

    # List what was moved
    echo -e "${INFO} APKs in $vuln_apk_dir:"
    ls -la "$vuln_apk_dir"/*.apk 2>/dev/null || true

    return 0
}

# Build APK using setup_app_source.sh
build_apk() {
    echo -e "${INFO} Building APK using setup_app_source.sh..."

    cd "$APP_DIR"

    if ! ./setup_app_source.sh; then
        echo -e "${ERROR} APK build failed"
        cd "$ROOT_DIR"
        return 1
    fi

    cd "$ROOT_DIR"

    # Validate APK was created
    local apk_dir="$APP_DIR/apk"
    local apk_count
    apk_count=$(find "$apk_dir" -maxdepth 1 -name "*.apk" -type f 2>/dev/null | wc -l)

    if [ "$apk_count" -eq 0 ]; then
        echo -e "${ERROR} Build completed but no APK found in $apk_dir"
        return 1
    fi

    echo -e "${SUCCESS} APK build completed - found $apk_count APK(s)"
    return 0
}

# Main logic
main() {
    echo -e "${INFO} =================================="
    echo -e "${INFO} APK Build Wrapper"
    echo -e "${INFO} =================================="
    echo -e "${INFO} App: $APP_NAME"
    echo -e "${INFO} App directory: $APP_DIR"

    if [ -n "$VULN_ID" ]; then
        echo -e "${INFO} Mode: Vulnerable APK build ($VULN_ID)"

        # Validate vulnerability directory exists
        local vuln_dir="$APP_DIR/synthetic_vulnerabilities/$VULN_ID"
        if [ ! -d "$vuln_dir" ]; then
            echo -e "${ERROR} Vulnerability directory not found: $vuln_dir"
            exit 1
        fi

        if [ ! -f "$vuln_dir/vulnerability.patch" ]; then
            echo -e "${ERROR} vulnerability.patch not found in $vuln_dir"
            exit 1
        fi
    else
        echo -e "${INFO} Mode: Regular APK build"
    fi

    echo -e "${INFO} =================================="

    # Step 1: Check submodule is initialized
    check_submodule_initialized || exit 1

    # Step 2: Checkout the correct commit
    checkout_commit || exit 1

    if [ -n "$VULN_ID" ]; then
        # Building vulnerable APK

        # Step 3: Backup existing APKs
        backup_existing_apks || exit 1

        # Step 4: Apply vulnerability patch
        if ! apply_vulnerability_patch "$VULN_ID"; then
            echo -e "${ERROR} Failed to apply vulnerability patch"
            restore_backed_up_apks
            exit 1
        fi

        # Step 5: Build APK
        if ! build_apk; then
            echo -e "${ERROR} APK build failed"
            restore_backed_up_apks
            # Restore clean codebase
            checkout_commit || true
            exit 1
        fi

        # Step 6: Move APKs to vuln directory
        if ! move_apks_to_vuln_dir "$VULN_ID"; then
            echo -e "${ERROR} Failed to move APKs to vuln directory"
            restore_backed_up_apks
            exit 1
        fi

        # Step 7: Restore original APKs
        restore_backed_up_apks || true

        # Step 8: Restore clean codebase state
        echo -e "${INFO} Restoring clean codebase state..."
        checkout_commit || true

        echo -e "${SUCCESS} =================================="
        echo -e "${SUCCESS} Vulnerable APK build completed!"
        echo -e "${SUCCESS} APK location: apps/$APP_NAME/apk/$VULN_ID/"
        echo -e "${SUCCESS} =================================="
    else
        # Regular build - just run setup_app_source.sh

        # Step 3: Build APK
        build_apk || exit 1

        echo -e "${SUCCESS} =================================="
        echo -e "${SUCCESS} Regular APK build completed!"
        echo -e "${SUCCESS} APK location: apps/$APP_NAME/apk/"
        echo -e "${SUCCESS} =================================="
    fi
}

# Run main
main "$@"
