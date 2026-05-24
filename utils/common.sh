#!/usr/bin/env bash
set -euo pipefail

_CLR_YELLOW=$'\033[1;33m'
_CLR_RED=$'\033[1;31m'
_CLR_RESET=$'\033[0m'

# Python logger re-tags captured shell stdout, so `log_info` doesn't add
# its own [INFO] tag. log_warn / log_error keep their tags: command_executor
# drains stderr through logger.info, so the inline tag is the only surviving
# level marker until that's fixed.
log_info()  { printf '%s\n' "$*"; }
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
