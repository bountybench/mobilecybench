#!/usr/bin/env bash
set -euo pipefail
UTIL_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="/mobilecybench"
if [[ ! -f "/.dockerenv" ]]; then
    if git_root="$(git -C "$UTIL_SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null)"; then
        ROOT_DIR="$git_root"
    else
        ROOT_DIR="$(cd "$UTIL_SCRIPT_DIR/.." && pwd)"
    fi
fi
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
source "$(dirname "${BASH_SOURCE[0]}")/wait.sh"
source "$(dirname "${BASH_SOURCE[0]}")/docker.sh"

# Installs an APK on the connected Android emulator.
adb_install_apk() {
    local apk_path=$1
    if [[ -z "$apk_path" ]]; then
        fatal "adb_install_apk requires an apk path"
    fi
    if [[ ! -f "$apk_path" ]]; then
        fatal "APK not found at $apk_path"
    fi
    wait_for_device_boot 120 || fatal "Device not ready for APK install"
    adb install -r "$apk_path"
}

# Launches a specific activity on the Android emulator.
adb_launch_activity() {
    local package_activity=$1
    if [[ -z "$package_activity" ]]; then
        fatal "adb_launch_activity needs component like 'org.package/.MainActivity'"
    fi
    adb shell am start -n "$package_activity" || fatal "Failed to start activity $package_activity"
}

# Computes hashes of files in given directories and outputs JSON.
adb_hash_dirs() {
    if [[ $# -eq 0 ]]; then
        fatal "adb_hash_dirs requires at least one directory"
    fi
    if ! command -v jq >/dev/null 2>&1; then
        fatal "adb_hash_dirs requires 'jq' to build JSON"
    fi
    for d in "$@"; do
        local combined=$(adb shell "find \"$d\" -type f -exec sha256sum {} + 2>/dev/null || true" \
            | awk '{print $1}' | sort | sha256sum | awk '{print $1}' || true)
        jq -n --arg dir "$d" --arg hash "${combined:-}" '{dir:$dir,hash:$hash}'
    done | jq -s 'reduce .[] as $item ({}; . + { ($item.dir): $item.hash }) | {dir_hashes: .}'
}

# Writes a UUID string to secret.txt in each specified device directory and appends UUID string to given file (i.e. secrets.json).
adb_hide_secret_files() {
    local out="${1:-secrets.json}"; shift
    if [[ $# -eq 0 ]]; then
        fatal "At least one directory required"
    fi
    command -v uuidgen >/dev/null 2>&1 || fatal "uuidgen not found"
    command -v jq >/dev/null 2>&1 || fatal "jq not found"
    local uuid=$(uuidgen) || fatal "uuidgen failed"
    local completed=true
    for d in "$@"; do
        local remote="${d%/}/secret.txt"
        adb shell "mkdir -p '${d//\'/\'\\\'\'}'" >/dev/null 2>&1 || log_warn "mkdir failed for $d (may be read-only)"
        if adb shell "echo -n '$uuid' > '$remote'" 2>/dev/null; then
            log_info "Wrote secret to device:$remote"
        else
            completed=false
            log_warn "Failed writing to $remote"
        fi
    done
    if $completed; then
        if [[ -f "$out" ]]; then
            if jq -e 'type == "array"' "$out" >/dev/null 2>&1; then
                jq --arg u "$uuid" '{credentials: ., sandbox: $u}' "$out" > "$out.tmp"
            else
                jq --arg u "$uuid" '. + {sandbox: $u}' "$out" > "$out.tmp"
            fi
            mv "$out.tmp" "$out"
        else
            jq -n --arg u "$uuid" '{sandbox: $u}' > "$out"
        fi
        log_info "Updated sandbox_uuid in $out"
    else
        log_warn "No secrets written; skipping JSON update"
    fi
}

# Resolves the APK path for an app, supporting --apk override.
# Usage: APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "app_name" "$@")
# Single source of truth for the per-variant APK subdirectory under
# apps/<app>/. Returns "apk/obfuscated" when MCB_OBFUSCATE=1, else "apk".
# All shell callers that need to construct an APK path should route through
# this rather than re-implementing the ternary, so layout changes happen
# in one place.
mcb_apk_subdir() {
    if [ "${MCB_OBFUSCATE:-0}" = "1" ]; then
        echo "apk/obfuscated"
    else
        echo "apk"
    fi
}

parse_apk_path() {
    local script_dir="$1" app_name="$2"; shift 2
    # Default path honors MCB_OBFUSCATE via mcb_apk_subdir so callers running
    # in an obfuscated experiment install the R8-minified build rather than
    # silently picking up a stale un-minified APK at apk/<app>.apk. Explicit
    # --apk always wins.
    local apk_path="$script_dir/$(mcb_apk_subdir)/${app_name}.apk"
    while [[ $# -gt 0 ]]; do
        case $1 in
            --apk)
                [[ "$2" = /* ]] && apk_path="$2" || apk_path="$script_dir/$2"
                shift 2 ;;
            *) shift ;;
        esac
    done
    echo "$apk_path"
}
