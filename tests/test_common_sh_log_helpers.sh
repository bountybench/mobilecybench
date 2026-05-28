#!/usr/bin/env bash
# Behavior tests for utils/common.sh::log_info / log_warn / log_error.
#
# log_info drops its inline [INFO] prefix (Python logger re-tags captured
# shell stdout). log_warn / log_error keep [WARN] / [ERROR] because
# command_executor flattens stderr to logger.info.

set -euo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$TEST_DIR")"
COMMON_SH="$REPO_ROOT/utils/common.sh"
[ -f "$COMMON_SH" ] || { echo "FAIL: utils/common.sh not found"; exit 1; }

run_case() {
    local name="$1"; local expected="$2"; shift 2
    local actual
    actual=$("$@" 2>&1)
    if [[ "$actual" == "$expected" ]]; then
        echo "PASS: $name"
    else
        echo "FAIL: $name"
        echo "  expected: $expected"
        echo "  actual:   $actual"
        exit 1
    fi
}

run_case "log_info has no inline prefix" \
    "hi" \
    bash -c "source '$COMMON_SH'; log_info hi"

# log_warn output contains ANSI escapes; strip them before comparing.
strip_ansi() {
    local raw; raw=$(cat)
    printf '%s' "$raw" | sed $'s/\x1b\\[[0-9;]*m//g'
}

actual=$(bash -c "source '$COMMON_SH'; log_warn 'uh oh'" 2>&1 | strip_ansi)
if [[ "$actual" == "[WARN]  uh oh" ]]; then
    echo "PASS: log_warn keeps [WARN] prefix"
else
    echo "FAIL: log_warn prefix lost"
    echo "  actual: $actual"
    exit 1
fi

actual=$(bash -c "source '$COMMON_SH'; log_error 'broke'" 2>&1 | strip_ansi)
if [[ "$actual" == "[ERROR] broke" ]]; then
    echo "PASS: log_error keeps [ERROR] prefix"
else
    echo "FAIL: log_error prefix lost"
    echo "  actual: $actual"
    exit 1
fi

echo "all 3 helpers behave as expected"
