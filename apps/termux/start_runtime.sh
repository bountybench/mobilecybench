#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "termux" "$@")
cd "$SCRIPT_DIR"

TERMUX_PACKAGE="com.termux"
TERMUX_LOCAL_REPO_URL="http://10.0.2.2:8087"
TERMUX_LOCAL_REPO_HOST_URL="http://127.0.0.1:8087"

log_info "Setting up Termux app..."

log_info "Building deterministic Termux local repo..."
"$SCRIPT_DIR/local_repo/build_repo.sh" >/dev/null

log_info "Starting Termux local repo service..."
docker compose down --volumes --remove-orphans 2>/dev/null || true
docker compose up -d --remove-orphans
wait_healthy termux-local-repo 60 || fatal "termux-local-repo did not become healthy"
curl -fsS "$TERMUX_LOCAL_REPO_HOST_URL/dists/mobilecybench/Release" >/dev/null \
    || fatal "Termux local repo did not serve Release metadata"

log_info "Setting SELinux to permissive..."
adb shell su 0 setenforce 0 2>/dev/null || log_warn "Could not set SELinux to permissive."

log_info "Installing Termux APK..."
adb_install_apk "$APK_PATH" >/dev/null

log_info "Clearing stale exploit app install..."
adb uninstall com.mobilecybench.exploit >/dev/null 2>&1 || true

log_info "Launching Termux..."
adb shell am start -n "$TERMUX_PACKAGE/.app.TermuxActivity" >/dev/null 2>&1 || true

log_info "Waiting for bootstrap to complete..."
for i in $(seq 1 30); do
    if adb shell su 0 test -d /data/data/com.termux/files/usr/bin 2>/dev/null; then
        log_info "Bootstrap completed after ${i}s"
        break
    fi
    sleep 1
done

log_info "Requesting storage permission for Termux..."
adb shell pm grant "$TERMUX_PACKAGE" android.permission.WRITE_EXTERNAL_STORAGE >/dev/null 2>&1 || true
adb shell appops set "$TERMUX_PACKAGE" MANAGE_EXTERNAL_STORAGE allow >/dev/null 2>&1 || true
adb shell appops set "$TERMUX_PACKAGE" LEGACY_STORAGE allow >/dev/null 2>&1 || true
adb shell am broadcast -a com.termux.REQUEST_PERMISSIONS >/dev/null 2>&1
sleep 2

log_info "Setting up storage symlinks..."
adb shell am start -n "$TERMUX_PACKAGE/.app.TermuxActivity" --es extraReloadStyle storage >/dev/null 2>&1
sleep 5

log_info "Creating setup anchor for a fresh Termux runtime..."
python3 probe_utils.py create-anchor >/dev/null

log_info "Configuring Termux to use the controlled local repo and priming the online golden flow..."
python3 probe_utils.py prepare-online-flow --repo-url "$TERMUX_LOCAL_REPO_URL" >/dev/null

log_info "Setting up user configuration files from deterministic seed data..."
if [ ! -f "$SCRIPT_DIR/setup_user_files.sh" ]; then
    fatal "setup_user_files.sh is required for deterministic Termux setup"
fi
"$SCRIPT_DIR/setup_user_files.sh"

python3 probe_utils.py attest-baseline >/dev/null

log_info "Termux setup completed successfully."
