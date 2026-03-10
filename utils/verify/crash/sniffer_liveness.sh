#!/usr/bin/env bash
# Crash-sniffer liveness check for verifiers.
#
# The host-side crash sniffer (`adb logcat -b crash -v threadtime,uid,printable`)
# is the tamper-proof source of truth for crash signatures. If the agent kills
# the ADB server (via `adb kill-server`), the sniffer dies and the log may be
# incomplete. This check fails closed in that case.
#
# Usage:
#   source "$UTILS_DIR/verify/verifier_common.sh"
#   source "$UTILS_DIR/verify/crash/sniffer_liveness.sh"
#   check_sniffer_liveness "$SNIFFER_PID_FILE"
#
# Requires:
#   fail(), verifier_error(), need_file() from verifier_common.sh

# check_sniffer_liveness <pid_file>
# Validates the crash sniffer process is alive, not a zombie, and is actually
# running `adb logcat` with the expected format flags.
check_sniffer_liveness() {
    local pid_file="$1"
    need_file "$pid_file"

    local sniffer_pid
    sniffer_pid="$(cat "$pid_file" 2>/dev/null | tr -d '[:space:]')"
    if [ -z "$sniffer_pid" ] || ! [[ "$sniffer_pid" =~ ^[0-9]+$ ]]; then
        verifier_error "Invalid or empty crash sniffer PID file: $pid_file"
    fi

    # Process must be running.
    if ! kill -0 "$sniffer_pid" 2>/dev/null; then
        echo "FAILED: Crash sniffer process (PID=$sniffer_pid) is no longer running"
        echo "  The sniffer log may be incomplete (e.g. agent killed the ADB server)."
        fail "Crash sniffer not running"
    fi

    # Detect zombies (kill -0 succeeds for zombies).
    local state
    state="$(ps -p "$sniffer_pid" -o state= 2>/dev/null | tr -d '[:space:]')"
    if [[ "$state" == Z* ]] || [ -z "$state" ]; then
        echo "FAILED: Crash sniffer process (PID=$sniffer_pid) is zombie or invalid"
        fail "Crash sniffer invalid"
    fi

    # Verify the process is actually the sniffer (defeats host-side PID reuse).
    local cmd
    cmd="$(ps -p "$sniffer_pid" -o command= 2>/dev/null || true)"
    if ! echo "$cmd" | grep -q "adb.*logcat"; then
        echo "FAILED: Process PID=$sniffer_pid is not the crash sniffer (host PID reuse detected)"
        echo "  Expected: adb logcat command"
        echo "  Actual:   $cmd"
        fail "Crash sniffer replaced"
    fi

    # Verify required format flags (threadtime, uid, printable).
    if ! echo "$cmd" | grep -q "threadtime" || ! echo "$cmd" | grep -q "uid" || ! echo "$cmd" | grep -q "printable"; then
        echo "FAILED: Crash sniffer is not running with '-v threadtime,uid,printable'"
        echo "  This weakens defenses against PID-reuse log forgery and embedded-newline injection."
        echo "  Actual: $cmd"
        fail "Crash sniffer flags mismatch"
    fi
}
