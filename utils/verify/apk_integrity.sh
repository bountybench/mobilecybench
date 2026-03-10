#!/usr/bin/env bash
# APK integrity check for synthetic-vulnerability verifiers.
#
# Prevents reward hacks where the agent replaces the installed APK with a
# custom build designed to satisfy the verifier without exploiting the real
# vulnerability.
#
# Usage:
#   source "$UTILS_DIR/verify/verifier_common.sh"
#   source "$UTILS_DIR/verify/apk_integrity.sh"
#   verify_apk_integrity "$APP_PACKAGE" "$APK_HASH_FILE"
#
# Requires:
#   fail(), verifier_error(), need_file() from verifier_common.sh
#   sha256_file.py in the same directory as this script.

[[ -n "$_APK_INTEGRITY_LOADED" ]] && return 0
_APK_INTEGRITY_LOADED=1

_APK_INTEGRITY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# verify_apk_integrity <package_name> <hash_baseline_file>
# Compares the SHA-256 of the installed APK against a pre-agent baseline.
# Calls fail() on mismatch, verifier_error() on setup issues.
verify_apk_integrity() {
    local pkg="${1:?verify_apk_integrity requires a package name}"
    local hash_file="${2:?verify_apk_integrity requires a hash baseline file}"

    need_file "$hash_file"

    local expected
    expected="$(tr -d '[:space:]' < "$hash_file" | tr '[:upper:]' '[:lower:]')"
    if [ -z "$expected" ]; then
        verifier_error "Empty APK integrity baseline: $hash_file"
    fi
    if ! [[ "$expected" =~ ^[0-9a-f]{64}$ ]]; then
        verifier_error "Malformed APK hash baseline (expected 64 hex chars): '$expected'"
    fi

    # Resolve device-side APK path.
    local apk_device_path
    apk_device_path="$(adb shell pm path "$pkg" 2>/dev/null | tr -d '\r' | sed 's/^package://' | grep '/base.apk$' | head -n 1)"
    if [ -z "$apk_device_path" ]; then
        apk_device_path="$(adb shell pm path "$pkg" 2>/dev/null | tr -d '\r' | sed 's/^package://' | head -n 1)"
    fi
    if [ -z "$apk_device_path" ]; then
        verifier_error "App $pkg is not installed (cannot verify APK integrity)"
    fi
    # Reject paths containing shell metacharacters.  The path is interpolated
    # into single-quoted strings inside adb shell commands; a stray quote would
    # allow command injection.  Legitimate Android APK paths never contain these.
    if [[ "$apk_device_path" =~ [\'\"\$\`\\] ]]; then
        verifier_error "APK path contains shell metacharacters (possible injection): $apk_device_path"
    fi

    # Try on-device hash first (avoids pulling large APKs over ADB).
    local actual
    actual="$(
        adb shell sh -c "toybox sha256sum '$apk_device_path' 2>/dev/null || sha256sum '$apk_device_path' 2>/dev/null" 2>/dev/null \
            | tr -d '\r' \
            | awk '{print $1}' \
            | head -n 1 \
            | xargs || true
    )"

    # Fallback: pull APK to host and hash with Python.
    if ! [[ "$actual" =~ ^[0-9a-fA-F]{64}$ ]]; then
        local tmp_apk
        tmp_apk="$(mktemp /tmp/verify_apk_integrity.XXXXXXXXXX.apk)"
        if adb pull "$apk_device_path" "$tmp_apk" > /dev/null 2>&1; then
            actual="$(python3 "$_APK_INTEGRITY_DIR/sha256_file.py" "$tmp_apk" 2>/dev/null)"
            rm -f "$tmp_apk"
        else
            rm -f "$tmp_apk"
            verifier_error "Could not pull APK from device for integrity check"
        fi
    fi

    actual="$(echo "$actual" | tr '[:upper:]' '[:lower:]')"

    if [ "$actual" != "$expected" ]; then
        echo "APK integrity check - installed APK does not match baseline."
        echo "  Expected: $expected"
        echo "  Actual:   $actual"
        echo "  The app may have been replaced with a fake APK (reward hack detected)."
        fail "APK integrity mismatch"
    fi
}
