#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "termux" "$@")
cd "$SCRIPT_DIR"

log_info "Setting up Termux app..."

log_info "Setting SELinux to permissive..."
adb shell su 0 setenforce 0 2>/dev/null || log_warn "Could not set SELinux to permissive."

# Pin to the first connected device to avoid "more than one device" error
DEVICE_SERIAL=$(adb devices | awk 'NR>1 && $2=="device"{print $1; exit}')
log_info "Using device: $DEVICE_SERIAL"

# Install the APK (custom flags: -t for test, -d for downgrade)
log_info "Installing Termux APK..."
adb -s "$DEVICE_SERIAL" install -r -t -d "$APK_PATH"
log_info "Termux installed successfully"

log_info "Launching Termux..."
adb -s "$DEVICE_SERIAL" shell "am start -n com.termux/.app.TermuxActivity" >/dev/null 2>&1 || true
sleep 5

log_info "Requesting storage permission for Termux..."
adb -s "$DEVICE_SERIAL" shell am broadcast -a com.termux.REQUEST_PERMISSIONS >/dev/null 2>&1
sleep 2

log_info "Setting up storage symlinks..."
adb -s "$DEVICE_SERIAL" shell am start -n com.termux/.app.TermuxActivity --es extraReloadStyle storage >/dev/null 2>&1
sleep 5

log_info "Setting up user configuration files from secrets.json..."
if [ -f "setup_user_files.sh" ]; then
    ./setup_user_files.sh
else
    log_warn "setup_user_files.sh not found, skipping user environment setup"
fi

log_info "Termux setup completed successfully!"
