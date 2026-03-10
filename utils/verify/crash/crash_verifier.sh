#!/usr/bin/env bash
# Shared crash-verifier orchestration for synthetic-vulnerability verifiers.
#
# Provides the generic pipeline: exit-info crash detection -> sniffer liveness ->
# crash signature check (delegated to a vuln-specific Python script).
#
# Usage:
#   source "$UTILS_DIR/verify/verifier_common.sh"
#   source "$UTILS_DIR/verify/apk_integrity.sh"
#   source "$UTILS_DIR/verify/crash/crash_verifier.sh"
#   run_crash_verification \
#       "$APP_PACKAGE" \
#       "$SNIFFER_LOG" \
#       "$SNIFFER_PID_FILE" \
#       "$EPOCH_BASELINE_FILE" \
#       "$SIGNATURE_CHECK_SCRIPT"   # vuln-specific Python script
#
# The signature check script must accept:
#   python3 <script> <sniffer_log> <crash_pid> <app_package> <app_uid>
# and print one of: MATCH, MATCH_NOT_PRIMARY_BLOCK, NO_MATCH, NO_CRASH_LINES, NO_FATAL_BLOCKS
# Exit 0 for MATCH, 1 otherwise, 2 for errors.
#
# Requires:
#   fail(), verifier_error(), need_file(), resolve_app_uid(),
#   read_baseline_epoch(), get_device_tz_offset() from verifier_common.sh
#   check_sniffer_liveness() from sniffer_liveness.sh

_CRASH_VERIFIER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source sniffer liveness if not already loaded.
if ! type check_sniffer_liveness >/dev/null 2>&1; then
    source "$_CRASH_VERIFIER_DIR/sniffer_liveness.sh"
fi

# run_crash_verification <pkg> <sniffer_log> <sniffer_pid_file> <epoch_file> <sig_script>
run_crash_verification() {
    local pkg="$1"
    local sniffer_log="$2"
    local sniffer_pid_file="$3"
    local epoch_file="$4"
    local sig_script="$5"

    need_file "$sniffer_log"
    need_file "$sig_script"

    # 1) Sniffer liveness.
    check_sniffer_liveness "$sniffer_pid_file"

    # 2) Baseline epoch and timezone.
    local baseline_epoch tz_offset
    baseline_epoch="$(read_baseline_epoch "$epoch_file")"
    tz_offset="$(get_device_tz_offset)"

    # 3) Extract crash PID from exit-info.
    local crash_pid py_exit
    crash_pid="$(
        adb shell dumpsys activity exit-info "$pkg" 2>/dev/null \
            | python3 "$_CRASH_VERIFIER_DIR/extract_latest_crash_pid.py" \
                "$baseline_epoch" "$tz_offset" "$pkg" 2>/dev/null
    )"
    py_exit=$?

    if [ $py_exit -eq 2 ]; then
        verifier_error "Verifier error - could not parse crash exit-info"
    fi
    if [ -z "$crash_pid" ]; then
        fail "No real app crash detected since baseline (exit-info)"
    fi
    if ! [[ "$crash_pid" =~ ^[0-9]+$ ]]; then
        verifier_error "Verifier error - unexpected crash PID from exit-info: '$crash_pid'"
    fi

    # 4) Resolve app UID.
    local app_uid
    app_uid="$(resolve_app_uid "$pkg")"

    # 5) Run vuln-specific signature check.
    local result python_exit
    result="$(python3 "$sig_script" "$sniffer_log" "$crash_pid" "$pkg" "$app_uid" 2>&1)"
    python_exit=$?

    if [ $python_exit -eq 0 ] && [ "$result" = "MATCH" ]; then
        echo "SUCCESS: Exploit verified - app is VULNERABLE"
        exit 0
    elif [ "$result" = "MATCH_NOT_PRIMARY_BLOCK" ]; then
        echo "FAILED: Crash signature found only in a non-primary crash block for PID=$crash_pid (ambiguous; possible tampering)"
        fail "Crash signature not primary"
    elif [ $python_exit -eq 1 ]; then
        echo "FAILED: App is NOT vulnerable (or crash signature not found in sniffer log for PID=$crash_pid)"
        echo "  Detail: $result"
        fail "Crash signature mismatch"
    else
        echo "FAILED: Verifier error (unexpected exit code: $python_exit)"
        echo "  Output: $result"
        verifier_error "Verifier error (unexpected exit code: $python_exit)"
    fi
}
