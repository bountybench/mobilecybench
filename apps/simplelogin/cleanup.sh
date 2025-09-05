#!/bin/bash

# SimpleLogin MobileCybench Cleanup Script
# Properly tears down all components: app, backend, and temporary files

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
METADATA_FILE="$SCRIPT_DIR/metadata.json"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[CLEANUP]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[CLEANUP]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[CLEANUP]${NC} $1"
}

log_error() {
    echo -e "${RED}[CLEANUP]${NC} $1"
}

cleanup_app() {
    log_info "Cleaning up SimpleLogin app..."
    
    if [[ ! -f "$METADATA_FILE" ]]; then
        log_warning "metadata.json not found, skipping app cleanup"
        return 0
    fi
    
    local app_id
    app_id=$(jq -r '.app_id' "$METADATA_FILE" 2>/dev/null || echo "")
    
    if [[ -z "$app_id" ]]; then
        log_warning "Could not determine app ID, skipping app uninstall"
        return 0
    fi
    
    # Check if adb is available
    if ! command -v adb &> /dev/null; then
        log_warning "adb not found, skipping app cleanup"
        return 0
    fi
    
    # Check if any device is connected
    if ! adb devices | grep -q "device$"; then
        log_warning "No Android device connected, skipping app cleanup"
        return 0
    fi
    
    # Uninstall the app
    log_info "Uninstalling app: $app_id"
    if adb uninstall "$app_id" 2>/dev/null; then
        log_success "App uninstalled successfully"
    else
        log_warning "App uninstall failed or app was not installed"
    fi
    
    # Stop the app if it's running
    log_info "Force stopping app if running..."
    adb shell am force-stop "$app_id" 2>/dev/null || true
    
    # Clear app data if any remains
    adb shell pm clear "$app_id" 2>/dev/null || true
}

cleanup_backend() {
    log_info "Cleaning up backend services..."
    
    cd "$SCRIPT_DIR"
    
    # Stop and remove Docker containers
    if command -v docker-compose &> /dev/null; then
        log_info "Stopping docker-compose services..."
        docker-compose down --volumes --remove-orphans 2>/dev/null || {
            log_warning "docker-compose down failed, trying individual container cleanup"
        }
        
        # Remove any lingering containers with SimpleLogin in the name
        local containers
        containers=$(docker ps -a --filter "name=simplelogin" -q 2>/dev/null || echo "")
        
        if [[ -n "$containers" ]]; then
            log_info "Removing SimpleLogin containers..."
            echo "$containers" | xargs docker rm -f 2>/dev/null || true
        fi
        
        # Remove volumes (optional - be careful with this)
        log_info "Cleaning up Docker volumes..."
        docker volume prune -f 2>/dev/null || true
        
    elif command -v docker &> /dev/null; then
        log_warning "docker-compose not found, trying docker cleanup..."
        
        # Stop containers with SimpleLogin in the name
        local containers
        containers=$(docker ps --filter "name=simplelogin" -q 2>/dev/null || echo "")
        
        if [[ -n "$containers" ]]; then
            log_info "Stopping SimpleLogin containers..."
            echo "$containers" | xargs docker stop 2>/dev/null || true
            echo "$containers" | xargs docker rm 2>/dev/null || true
        fi
    else
        log_warning "Docker not found, skipping container cleanup"
    fi
    
    log_success "Backend cleanup completed"
}

cleanup_temp_files() {
    log_info "Cleaning up temporary files..."
    
    cd "$SCRIPT_DIR"
    
    # List of temporary files to remove
    local temp_files=(
        "secrets.json"
        "apk_path.txt"
        "integrity_baseline.json"
        "*_results.json"
        "scores.json"
        "*.log"
        "*.tmp"
    )
    
    for pattern in "${temp_files[@]}"; do
        # Use find to handle wildcards safely
        find . -maxdepth 1 -name "$pattern" -type f 2>/dev/null | while read -r file; do
            if [[ -f "$file" ]]; then
                log_info "Removing: $file"
                rm -f "$file"
            fi
        done
    done
    
    # Clean up codebase directory if it exists
    if [[ -d "$SCRIPT_DIR/codebase" ]]; then
        log_info "Removing codebase directory..."
        rm -rf "$SCRIPT_DIR/codebase"
    fi
    
    # Clean up build artifacts in codebase
    if [[ -d "$SCRIPT_DIR/codebase" ]]; then
        log_info "Cleaning build artifacts..."
        find "$SCRIPT_DIR/codebase" -name "build" -type d -exec rm -rf {} + 2>/dev/null || true
        find "$SCRIPT_DIR/codebase" -name "*.apk" -type f -delete 2>/dev/null || true
    fi
    
    log_success "Temporary files cleanup completed"
}

cleanup_emulator() {
    log_info "Cleaning up emulator (if managed by this script)..."
    
    # Check if emulator is running
    if command -v adb &> /dev/null && adb devices | grep -q "emulator.*device"; then
        log_info "Emulator is running, leaving it running (may be used by other apps)"
        # Note: We don't automatically stop the emulator as it might be shared
    fi
    
    # Kill any background emulator processes started by this script
    # (This is risky, so we'll be conservative and just report)
    local emulator_pids
    emulator_pids=$(pgrep -f "emulator.*avd" 2>/dev/null || echo "")
    
    if [[ -n "$emulator_pids" ]]; then
        log_info "Found running emulator processes (not terminating automatically)"
        log_info "To manually stop emulator, run: adb emu kill"
    fi
}

verify_cleanup() {
    log_info "Verifying cleanup..."
    
    local issues_found=0
    
    # Check if app is still installed
    if command -v adb &> /dev/null && adb devices | grep -q "device$"; then
        local app_id
        app_id=$(jq -r '.app_id' "$METADATA_FILE" 2>/dev/null || echo "")
        
        if [[ -n "$app_id" ]] && adb shell pm list packages | grep -q "$app_id"; then
            log_warning "App $app_id is still installed"
            ((issues_found++))
        fi
    fi
    
    # Check if Docker containers are still running
    if command -v docker &> /dev/null; then
        local running_containers
        running_containers=$(docker ps --filter "name=simplelogin" -q 2>/dev/null || echo "")
        
        if [[ -n "$running_containers" ]]; then
            log_warning "SimpleLogin containers still running"
            ((issues_found++))
        fi
    fi
    
    # Check for remaining temp files
    if [[ -f "$SCRIPT_DIR/secrets.json" ]]; then
        log_warning "secrets.json still exists"
        ((issues_found++))
    fi
    
    if [[ $issues_found -eq 0 ]]; then
        log_success "Cleanup verification passed"
        return 0
    else
        log_warning "Cleanup verification found $issues_found issues"
        return 1
    fi
}

show_cleanup_summary() {
    echo
    echo "=" * 50
    echo "CLEANUP SUMMARY"
    echo "=" * 50
    echo "✅ App uninstalled (if installed)"
    echo "✅ Backend containers stopped"
    echo "✅ Temporary files removed"
    echo "✅ Docker volumes cleaned"
    echo
    echo "Note: Emulator is left running (may be shared)"
    echo "To manually stop emulator: adb emu kill"
    echo "=" * 50
}

main() {
    log_info "Starting SimpleLogin MobileCybench cleanup..."
    
    # Perform cleanup in reverse order of setup
    cleanup_app
    cleanup_backend
    cleanup_temp_files
    cleanup_emulator
    
    # Verify cleanup was successful
    if verify_cleanup; then
        log_success "Cleanup completed successfully!"
    else
        log_warning "Cleanup completed with some issues (see above)"
    fi
    
    show_cleanup_summary
}

# Handle interrupts gracefully
cleanup_on_interrupt() {
    log_warning "Cleanup interrupted, but continuing..."
    exit 1
}

trap cleanup_on_interrupt INT TERM

# Run main function if script is executed directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
