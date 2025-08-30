#!/usr/bin/env bash
set -euo pipefail

log_info()  { printf '%s\n' "[INFO]  $*"; }
log_warn()  { printf '%s\n' "[WARN]  $*" >&2; }
log_error() { printf '%s\n' "[ERROR] $*" >&2; }
log()  { local tag="$1"; shift || true; printf '%s\n' "[$tag] $*"; }

fatal() {
    local msg="$1"; local rc=${2:-1}
    log_error "$msg"
    exit "$rc"
}

# Ensures a required command is available.
require_cmd() {
    local cmd=$1
    if ! command -v "$cmd" >/dev/null 2>&1; then
        fatal "Required command '$cmd' not found"
    fi
}

# Changes directory safely, logging the action.
safe_cd() {
    local dir=$1
    if [[ -z "$dir" ]]; then
        fatal "safe_cd: missing directory argument"
    fi
    log_info "cd $dir"
    cd "$dir" || fatal "Failed to cd into $dir"
}
