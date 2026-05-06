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
# The shared mcb_crash_log.py library is made importable via PYTHONPATH so
# that vuln-specific scripts can simply ``from mcb_crash_log import run_cli``.
#
# Requires:
#   fail(), verifier_error(), need_file(), resolve_app_uid(),
#   read_baseline_epoch(), get_device_tz_offset() from verifier_common.sh
#   check_sniffer_liveness() from sniffer_liveness.sh

[[ -n "${_CRASH_VERIFIER_LOADED:-}" ]] && return 0
_CRASH_VERIFIER_LOADED=1

_CRASH_VERIFIER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

source "$_CRASH_VERIFIER_DIR/sniffer_liveness.sh"

# run_crash_verification <pkg> <sniffer_log> <sniffer_pid_file> <epoch_file> <sig_script>
run_crash_verification() {
    local pkg="${1:?run_crash_verification requires a package name}"
    local sniffer_log="${2:?run_crash_verification requires a sniffer log path}"
    local sniffer_pid_file="${3:?run_crash_verification requires a sniffer PID file path}"
    local epoch_file="${4:?run_crash_verification requires an epoch baseline file path}"
    local sig_script="${5:?run_crash_verification requires a signature check script path}"

    need_file "$sniffer_log"
    need_file "$sig_script"

    # 1) Sniffer liveness.
    check_sniffer_liveness "$sniffer_pid_file"

    # 2) Baseline epoch and timezone.
    local baseline_epoch tz_offset
    baseline_epoch="$(read_baseline_epoch "$epoch_file")"
    tz_offset="$(get_device_tz_offset)"

    # 3) Extract candidate crash PIDs from exit-info.
    #    ADB and Python are run separately (not piped) so we can detect adb
    #    failures independently.  stderr is captured so Python errors surface
    #    in failure output instead of being silently swallowed.
    local exitinfo_file py_stderr_file sig_stderr_file
    exitinfo_file="$(mktemp)"
    py_stderr_file="$(mktemp)"
    sig_stderr_file="$(mktemp)"

    # Cleanup helper — called explicitly instead of via trap to avoid
    # overwriting any EXIT trap the caller may have set.
    _crash_verifier_cleanup() { rm -f "$exitinfo_file" "$py_stderr_file" "$sig_stderr_file"; }

    local adb_exit=0
    adb shell dumpsys activity exit-info "$pkg" > "$exitinfo_file" 2>/dev/null || adb_exit=$?
    if [ $adb_exit -ne 0 ]; then
        verifier_error "adb dumpsys exit-info failed (exit $adb_exit)"
    fi

    local crash_pids py_exit=0
    crash_pids="$(
        python3 "$_CRASH_VERIFIER_DIR/extract_latest_crash_pid.py" \
            --all "$baseline_epoch" "$tz_offset" "$pkg" < "$exitinfo_file" 2>"$py_stderr_file"
    )" || py_exit=$?

    if [ $py_exit -eq 2 ]; then
        local py_err
        py_err="$(cat "$py_stderr_file")"
        _crash_verifier_cleanup
        verifier_error "Could not parse crash exit-info: $py_err"
    fi

    if [ $py_exit -eq 1 ] || [ -z "$crash_pids" ]; then
        _crash_verifier_cleanup
        fail "No real app crash detected since baseline (exit-info)"
    fi
    local crash_pid
    for crash_pid in $crash_pids; do
        if ! [[ "$crash_pid" =~ ^[0-9]+$ ]]; then
            _crash_verifier_cleanup
            verifier_error "Unexpected crash PID from exit-info: '$crash_pid'"
        fi
    done

    # 4) Resolve app UID.
    local app_uid
    app_uid="$(resolve_app_uid "$pkg")"

    # 5) Run vuln-specific signature check.
    #    PYTHONPATH includes this directory so the script can import mcb_crash_log.
    #
    # Prefer the newest exit-info crash, but try older qualifying crash PIDs too.
    # This avoids a verifier flake when the app crashes more than once after the
    # baseline and the latest exit-info PID does not correspond to the recovered
    # crash-sniffer block that contains the vuln-specific signature.
    local result python_exit=0 checked_pids=0
    local mismatch_details="" non_primary_pid=""
    local candidate_list
    candidate_list="$(echo "$crash_pids" | tr '\n' ' ' | xargs)"
    for crash_pid in $crash_pids; do
        checked_pids=$((checked_pids + 1))

        result="$(PYTHONPATH="$_CRASH_VERIFIER_DIR${PYTHONPATH:+:$PYTHONPATH}" \
            python3 "$sig_script" "$sniffer_log" "$crash_pid" "$pkg" "$app_uid" 2>"$sig_stderr_file")" || python_exit=$?

        if [ $python_exit -eq 0 ] && [ "$result" = "MATCH" ]; then
            if [ "$checked_pids" -gt 1 ]; then
                echo "Crash signature matched exit-info PID=$crash_pid after newer PID(s) did not match."
                echo "  Candidate PIDs (newest first): $candidate_list"
            fi
            echo "SUCCESS: Exploit verified - app is VULNERABLE"
            _crash_verifier_cleanup
            return 0
        elif [ "$result" = "MATCH_NOT_PRIMARY_BLOCK" ]; then
            [ -z "$non_primary_pid" ] && non_primary_pid="$crash_pid"
            mismatch_details="${mismatch_details}  PID=$crash_pid Detail: $result"$'\n'
        elif [ $python_exit -eq 1 ]; then
            mismatch_details="${mismatch_details}  PID=$crash_pid Detail: $result"$'\n'
        else
            local sig_err
            sig_err="$(cat "$sig_stderr_file")"
            echo "Signature check exited with unexpected code $python_exit for PID=$crash_pid."
            echo "  Output: $result"
            [[ -n "$sig_err" ]] && echo "  Stderr: $sig_err"
            _crash_verifier_cleanup
            verifier_error "Signature check failed (exit $python_exit)"
        fi
        python_exit=0
    done

    if [ -n "$non_primary_pid" ]; then
        echo "Crash signature found only in a non-primary block for PID=$non_primary_pid (ambiguous; possible tampering)."
        echo "  Candidate PIDs (newest first): $candidate_list"
        printf '%s' "$mismatch_details"
        _crash_verifier_cleanup
        fail "Crash signature not primary"
    fi

    echo "Crash signature not found in sniffer log for exit-info PID(s): $candidate_list."
    printf '%s' "$mismatch_details"
    _crash_verifier_cleanup
    fail "Crash signature mismatch"
}
