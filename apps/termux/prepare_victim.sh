#!/usr/bin/env bash
# Re-seed Termux's app-private state so probes have a coherent baseline.
#
# The remote_attacker phase runs `adb shell pm clear com.termux` between
# exploit.sh and probe evaluation, which wipes /data/data/com.termux —
# including the bootstrap unpacked by start_runtime.sh and the seed
# manifest written by attest-baseline. Without a re-seed, probes hit
# `BaselineError: bootstrap path missing or not directory:
# /data/data/com.termux/files/home` and the run scores as
# probe_evaluator_error.
#
# This script repeats the device-side setup_runtime path: relaunch
# Termux, wait for bootstrap, re-grant storage permissions, and
# re-create the seed manifest. Host-side state from start_runtime.sh
# (the local_repo container, the built APK on disk) is unaffected by
# pm clear and is not redone here.
#
# malicious_app does not call pm clear, so its bootstrap and seed
# survive into prepare_victim. The script is idempotent — repeating
# the storage-permission and seed steps against an already-good
# Termux is a no-op cost, not a correctness hazard.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
cd "$SCRIPT_DIR"

TERMUX_PACKAGE="com.termux"
TERMUX_LOCAL_REPO_URL="http://10.0.2.2:8087"
BOOTSTRAP_WAIT_SECONDS=${BOOTSTRAP_WAIT_SECONDS:-30}

log_info "Setting SELinux to permissive..."
adb shell su 0 setenforce 0 2>/dev/null || log_warn "Could not set SELinux to permissive."

log_info "Launching Termux to trigger bootstrap re-unpack..."
adb shell am start -n "$TERMUX_PACKAGE/.app.TermuxActivity" >/dev/null 2>&1 || true

log_info "Waiting for bootstrap to complete..."
bootstrap_ready=0
for i in $(seq 1 "$BOOTSTRAP_WAIT_SECONDS"); do
    if adb shell su 0 test -d /data/data/com.termux/files/usr/bin 2>/dev/null; then
        log_info "Bootstrap completed after ${i}s"
        bootstrap_ready=1
        break
    fi
    sleep 1
done
if [ "$bootstrap_ready" -ne 1 ]; then
    fatal "Termux bootstrap did not complete within ${BOOTSTRAP_WAIT_SECONDS}s"
fi

log_info "Re-granting storage permission for Termux..."
adb shell pm grant "$TERMUX_PACKAGE" android.permission.WRITE_EXTERNAL_STORAGE >/dev/null 2>&1 || true
adb shell appops set "$TERMUX_PACKAGE" MANAGE_EXTERNAL_STORAGE allow >/dev/null 2>&1 || true
adb shell appops set "$TERMUX_PACKAGE" LEGACY_STORAGE allow >/dev/null 2>&1 || true
adb shell am broadcast -a com.termux.REQUEST_PERMISSIONS >/dev/null 2>&1
sleep 2

log_info "Setting up storage symlinks..."
adb shell am start -n "$TERMUX_PACKAGE/.app.TermuxActivity" --es extraReloadStyle storage >/dev/null 2>&1
sleep 5

log_info "Recreating setup anchor..."
python3 probe_utils.py create-anchor >/dev/null

log_info "Re-priming online flow against the local repo..."
python3 probe_utils.py prepare-online-flow --repo-url "$TERMUX_LOCAL_REPO_URL" >/dev/null

log_info "Re-seeding user files from deterministic seed data..."
if [ ! -f "$SCRIPT_DIR/setup_user_files.sh" ]; then
    fatal "setup_user_files.sh is required for deterministic Termux setup"
fi
"$SCRIPT_DIR/setup_user_files.sh"

log_info "Re-attesting baseline manifest..."
python3 probe_utils.py attest-baseline >/dev/null

log_info "Termux victim state prepared."
