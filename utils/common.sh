#!/usr/bin/env bash
set -euo pipefail

_CLR_YELLOW=$'\033[1;33m'
_CLR_RED=$'\033[1;31m'
_CLR_RESET=$'\033[0m'

log_info()  { printf '%s\n' "[INFO]  $*"; }
log_warn()  { printf '%s\n' "${_CLR_YELLOW}[WARN]  $*${_CLR_RESET}" >&2; }
log_error() { printf '%s\n' "${_CLR_RED}[ERROR] $*${_CLR_RESET}" >&2; }
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
