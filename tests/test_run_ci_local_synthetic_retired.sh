#!/usr/bin/env bash
# Regression tests for retired synthetic-vulnerability local CI entrypoints.

set -euo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$TEST_DIR")"
RUN_CI="$REPO_ROOT/run_ci_local.sh"
[ -f "$RUN_CI" ] || { echo "FAIL: run_ci_local.sh not found at $RUN_CI"; exit 1; }

TMP="$(mktemp -d -t run_ci_synthetic_retired.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

# Source only the argument parser. Sourcing the full runner would initialize
# local error logging and later Docker/emulator setup; this keeps the test
# focused on the public CLI contract.
awk '
    /^# Parse command line arguments/ { capture = 1 }
    /^# Get API level from metadata/ { capture = 0 }
    capture { print }
' "$RUN_CI" > "$TMP/run_ci_parser.sh"

assert_grep() {
    local label="$1" pattern="$2" file="$3"
    if ! grep -Eq -- "$pattern" "$file"; then
        echo "FAIL: $label (pattern '$pattern' not in $file)"
        echo "--- $file ---"
        cat "$file" 2>/dev/null || true
        exit 1
    fi
    echo "PASS: $label"
}

assert_not_grep() {
    local label="$1" pattern="$2" file="$3"
    if grep -Eq -- "$pattern" "$file"; then
        echo "FAIL: $label (unexpected pattern '$pattern' in $file)"
        echo "--- $file ---"
        cat "$file"
        exit 1
    fi
    echo "PASS: $label"
}

run_rejected() {
    local label="$1"
    shift
    local output="$TMP/$label.log"

    set +e
    (DIR=""; source "$TMP/run_ci_parser.sh" "$@") > "$output" 2>&1
    local status=$?
    set -e

    if [ "$status" -eq 0 ]; then
        echo "FAIL: $label should reject retired synthetic mode"
        cat "$output"
        exit 1
    fi
    assert_grep "$label reports retired flag" "is retired" "$output"
    assert_grep "$label points to archive" "archive/synthetic-vulnerabilities" "$output"
    assert_not_grep "$label does not show usage noise" "^Usage:" "$output"
}

help_output="$TMP/help.log"
set +e
(DIR=""; source "$TMP/run_ci_parser.sh" --help) > "$help_output" 2>&1
help_status=$?
set -e
if [ "$help_status" -ne 0 ]; then
    echo "FAIL: --help should exit 0"
    cat "$help_output"
    exit 1
fi
assert_not_grep "help hides --test-synthetic-vuln" "--test-synthetic-vuln" "$help_output"
assert_not_grep "help hides --test-all-synthetic-vulns" "--test-all-synthetic-vulns" "$help_output"
assert_grep "help keeps zero-day task mode" "--test-zero-day-vuln" "$help_output"

run_rejected \
    "single_synthetic_vuln" \
    apps/conversations \
    --test-synthetic-vuln \
    synthetic_vulnerabilities/vuln_0
run_rejected "all_synthetic_vulns" apps/conversations --test-all-synthetic-vulns

echo
printf 'All tests passed.\n'
