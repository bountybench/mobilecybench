#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
source "$(dirname "${BASH_SOURCE[0]}")/wait.sh"


# Checks for required Android tools and SDK presence.
check_android_prereqs() {
    if ! command -v java >/dev/null 2>&1; then
        log_warn "java not found in PATH; building Android apps may fail"
    fi
    if ! command -v adb >/dev/null 2>&1; then
        log_warn "adb not found in PATH; emulator/device connectivity may fail"
    fi
    if [[ -z "${ANDROID_HOME:-}" ]]; then
        log_warn "ANDROID_HOME is not set; Android SDK may be unavailable"
    elif [[ ! -d "${ANDROID_HOME}" ]]; then
        log_warn "ANDROID_HOME is set to ${ANDROID_HOME} but directory does not exist"
    fi
    log_info "Android environment check complete."
    require_cmd java
    require_cmd git
    require_cmd adb
    log_info "Android prerequisites OK"
}

# Starts an Android emulator waits for it to boot.
start_emulator() {
    local avd_name=$1
    local start_script=${2:-"$(dirname "${BASH_SOURCE[0]}")/../start_emulator.sh"}
    if [[ -z "$avd_name" ]]; then
        fatal "start_emulator requires AVD name"
    fi
    if [[ ! -x "$start_script" ]]; then
        fatal "start emulator script not found/executable at $start_script"
    fi
    "$start_script" "$avd_name" &
    adb wait-for-device
    log_info "Emulator started (AVD=${avd_name})"
}

# Installs an APK on the connected Android emulator.
adb_install_apk() {
    local apk_path=$1
    if [[ -z "$apk_path" ]]; then
        fatal "adb_install_apk requires an apk path"
    fi
    if [[ ! -f "$apk_path" ]]; then
        fatal "APK not found at $apk_path"
    fi
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
