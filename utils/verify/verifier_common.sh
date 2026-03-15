#!/usr/bin/env bash
# Shared shell helpers for synthetic-vulnerability verifiers.
#
# Usage:
#   source "$SCRIPT_DIR/../../../utils/verify/verifier_common.sh"
#
# Provides:
#   fail <msg>              - Print FAILED and exit 1 (not vulnerable / exploit didn't work)
#   verifier_error <msg>    - Print FAILED and exit 2 (verifier setup/env problem)
#   need_file <path>        - verifier_error if file missing
#   resolve_app_uid <pkg>   - Print the numeric UID for the given package (or verifier_error)
#   read_baseline_epoch <file> - Print the integer epoch from the given file (or verifier_error)
#   get_device_tz_offset       - Print the device timezone offset like +0000 (or verifier_error)
#
# Note: all exit-calling helpers (fail, verifier_error) terminate the process.
# Functions in this library are designed for use in top-level verifier scripts,
# not inside subshells or conditional blocks where exit would be swallowed.

[[ -n "${_VERIFIER_COMMON_LOADED:-}" ]] && return 0
_VERIFIER_COMMON_LOADED=1

fail()           { echo "FAILED: $*"; exit 1; }
verifier_error() { echo "FAILED: $*"; exit 2; }
need_file() {
    if [ -z "$1" ]; then
        verifier_error "need_file called with empty path"
    fi
    if [ -L "$1" ]; then
        verifier_error "Refusing symlink (expected regular file): $1"
    fi
    [ -f "$1" ] || verifier_error "Missing required file: $1"
}

# resolve_app_uid <package>
# Prints the numeric UID for the installed package.
resolve_app_uid() {
    local pkg="${1:?resolve_app_uid requires a package name}"
    local uid=""

    # Method 1: pm list packages -U
    uid="$(
        adb shell pm list packages -U "$pkg" 2>/dev/null \
            | tr -d '\r' \
            | awk -F'uid:' '/uid:/{print $2; exit}' \
            | awk '{print $1}' \
            | tr -d '[:space:]' || true
    )"
    if [[ "$uid" =~ ^[0-9]+$ ]]; then echo "$uid"; return 0; fi

    # Method 2: dumpsys package
    uid="$(
        adb shell dumpsys package "$pkg" 2>/dev/null \
            | tr -d '\r' \
            | sed -n -E 's/.*(userId=|uid=|appId=)([0-9]+).*/\2/p' \
            | head -n 1 \
            | tr -d '[:space:]' || true
    )"
    if [[ "$uid" =~ ^[0-9]+$ ]]; then echo "$uid"; return 0; fi

    # Method 3: stat (requires root, best-effort)
    uid="$(
        adb shell su 0 stat -c %u "/data/data/$pkg" 2>/dev/null \
            | tr -d '\r' \
            | head -n 1 \
            | tr -d '[:space:]' || true
    )"
    if [[ "$uid" =~ ^[0-9]+$ ]]; then echo "$uid"; return 0; fi

    verifier_error "Could not determine app UID for $pkg (got: '$uid')"
}

# read_baseline_epoch <file>
# Prints the integer epoch stored in the given file.
read_baseline_epoch() {
    local f="${1:?read_baseline_epoch requires a file path}"
    need_file "$f"
    local val
    val="$(tr -d '[:space:]' < "$f")"
    if ! [[ "$val" =~ ^[0-9]+$ ]]; then
        verifier_error "Invalid device epoch baseline (expected integer): $f (got: '$val')"
    fi
    echo "$val"
}

# get_device_tz_offset
# Prints the device timezone offset string (e.g. +0000, -0800).
get_device_tz_offset() {
    local tz
    tz="$(adb shell date +%z 2>/dev/null | tr -d '\r' | head -n 1 | tr -d '[:space:]' || true)"
    if ! [[ "$tz" =~ ^[+-][0-9]{4}$ ]]; then
        verifier_error "Could not determine device timezone offset via 'date +%z' (got: '$tz')"
    fi
    echo "$tz"
}


