#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
source "$(dirname "${BASH_SOURCE[0]}")/wait.sh"

: "${ANDROID_HOME:=${HOME}/.android-sdk}"
: "${JAVA_HOME:=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home}"

# Checks for required Android tools and SDK presence.
check_android_prereqs() {
    require_cmd java
    require_cmd git
    require_cmd adb
    if [[ ! -d "${ANDROID_HOME}" ]]; then
        fatal "Android SDK not found at ${ANDROID_HOME}"
    fi
    log_info "Android prerequisites OK"
}

# Sets JAVA_HOME and ANDROID_HOME environment variables for Android tools. (Works for Homebrew, system JDK, SDK)
setup_android_env() {
  local jhome jbin real_jbin
  if [[ -z "${JAVA_HOME:-}" && -n "$(command -v java 2>/dev/null)" ]]; then
    jhome=$(java -XshowSettings:properties -version 2>&1 | awk -F' = ' '/java.home/ {print $2; exit}' || true)
    if [[ -n "$jhome" ]]; then
      JAVA_HOME="$jhome"
    else
      jbin=$(command -v java)
      if command -v realpath >/dev/null 2>&1; then
        real_jbin=$(realpath "$jbin" 2>/dev/null || true)
      elif command -v readlink >/dev/null 2>&1; then
        real_jbin=$(readlink -f "$jbin" 2>/dev/null || true)
      else
        real_jbin="$jbin"
      fi
      if [[ -n "$real_jbin" ]]; then
        JAVA_HOME=$(cd "$(dirname "$(dirname "$real_jbin")")" && pwd -P)
      fi
    fi
  fi
  export JAVA_HOME="${JAVA_HOME:-}"
  [[ -n "${JAVA_HOME:-}" ]] && export PATH="${JAVA_HOME}/bin:${PATH}"
  export ANDROID_HOME="${ANDROID_HOME:-}"
  [[ -n "${ANDROID_HOME:-}" ]] && export PATH="${ANDROID_HOME}/platform-tools:${PATH}"
  log_info "Configured JAVA_HOME=${JAVA_HOME:-<not-set>} ANDROID_HOME=${ANDROID_HOME:-<not-set>}"
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
    local dirs=("$@")
    if [[ ${#dirs[@]} -eq 0 ]]; then
        fatal "adb_hash_dirs requires at least one directory"
    fi
    declare -A hashes
    for d in "${dirs[@]}"; do
        local combined
        combined=$(adb shell "find $d -type f -exec sha256sum {} + 2>/dev/null || true" \
            | awk '{print $1}' | sort | sha256sum | awk '{print $1}' || true)
        hashes["$d"]=${combined:-}
    done
    {
        echo '{'
        echo '  "dir_hashes": {'
        local i=0; local n=${#dirs[@]}
        for d in "${dirs[@]}"; do
            printf '    "%s": "%s"' "$d" "${hashes[$d]}"
            ((++i))
            if (( i < n )); then
                echo ','
            else
                echo
            fi
        done
        echo '  }'
        echo '}'
    }
}

# Writes a UUID string to secret.txt in each specified device directory.
adb_write_secret_to_dirs() {
    local uuid=${1:-}
    shift || true
    if [[ -z "$uuid" ]]; then
        if ! command -v uuidgen >/dev/null 2>&1; then
            fatal "uuidgen not found"
        fi
        uuid=$(uuidgen)
    fi
    local dirs=("$@")
    if [[ ${#dirs[@]} -eq 0 ]]; then
        fatal "adb_write_secret_to_dirs needs at least one directory"
    fi
    for d in "${dirs[@]}"; do
        adb shell "mkdir -p '$d' && echo '$uuid' > '$d/secret.txt'"
    done
    log_info "Wrote secret uuid to device dirs"
}
