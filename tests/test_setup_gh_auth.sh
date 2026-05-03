#!/usr/bin/env bash
# Behavior tests for setup.sh::check_gh_auth.
#
# Cases:
#   1. gh not on PATH                  -> exit 1, install instructions
#   2. gh present but unauthenticated  -> exit 1, "gh auth login" guidance
#   3. gh present and authenticated    -> exit 0
#
# We extract the function from setup.sh and run it standalone with a mock
# `gh` binary on PATH whose exit code we control per case.

set -euo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$TEST_DIR")"
SETUP_SCRIPT="$REPO_ROOT/setup.sh"
[ -f "$SETUP_SCRIPT" ] || { echo "FAIL: setup.sh not found"; exit 1; }

TMP="$(mktemp -d -t setup_gh_auth_test.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

# Extract just check_gh_auth and provide stub helpers it depends on.
{
    cat <<'STUBS'
command_exists() { command -v "$1" >/dev/null 2>&1; }
log() { echo "[log] $*"; }
error_exit() { echo "[error_exit] $*" >&2; exit 1; }
STUBS
    awk '/^check_gh_auth\(\) \{/,/^\}/' "$SETUP_SCRIPT"
} > "$TMP/fn.sh"
grep -q '^check_gh_auth' "$TMP/fn.sh" || { echo "FAIL: could not extract check_gh_auth"; exit 1; }

# Build a mock `gh` whose `gh auth status` exit code is controlled by env.
mkdir -p "$TMP/bin"
cat > "$TMP/bin/gh" <<'MOCK'
#!/usr/bin/env bash
if [[ "$1" == "auth" && "$2" == "status" ]]; then
    exit "${MOCK_GH_AUTH_EXIT:-0}"
fi
exit 0
MOCK
chmod +x "$TMP/bin/gh"

# Run check_gh_auth in a subshell with a controlled PATH; return its exit
# code and combined stdout/stderr.
run_check() {
    local path_override="$1"
    set +e
    output=$(
        PATH="$path_override" bash -c "source '$TMP/fn.sh'; check_gh_auth" 2>&1
    )
    rc=$?
    set -e
}

# ---------------------------------------------------------------------
# Test 1: gh not on PATH
# ---------------------------------------------------------------------
echo "Test 1: gh missing"
run_check "/usr/bin:/bin"
[[ $rc -ne 0 ]] || { echo "FAIL: expected nonzero exit when gh missing"; exit 1; }
[[ "$output" == *"GitHub CLI ('gh') not found"* ]] \
    || { echo "FAIL: missing-gh message not in output"; echo "$output"; exit 1; }
[[ "$output" == *"gh auth login"* ]] \
    || { echo "FAIL: install instructions did not mention gh auth login"; echo "$output"; exit 1; }
echo "PASS: Test 1"

# ---------------------------------------------------------------------
# Test 2: gh present, gh auth status fails
# ---------------------------------------------------------------------
echo
echo "Test 2: gh present but unauthenticated"
MOCK_GH_AUTH_EXIT=1 run_check "$TMP/bin:/usr/bin:/bin"
[[ $rc -ne 0 ]] || { echo "FAIL: expected nonzero exit when gh unauthed"; exit 1; }
[[ "$output" == *"not authenticated"* ]] \
    || { echo "FAIL: unauth message missing"; echo "$output"; exit 1; }
[[ "$output" == *"gh auth login"* ]] \
    || { echo "FAIL: did not surface 'gh auth login'"; echo "$output"; exit 1; }
echo "PASS: Test 2"

# ---------------------------------------------------------------------
# Test 3: gh present, authenticated
# ---------------------------------------------------------------------
echo
echo "Test 3: gh authenticated"
MOCK_GH_AUTH_EXIT=0 run_check "$TMP/bin:/usr/bin:/bin"
[[ $rc -eq 0 ]] || { echo "FAIL: expected exit 0 when gh authed; got $rc"; echo "$output"; exit 1; }
[[ "$output" == *"authenticated"* ]] \
    || { echo "FAIL: success log missing"; echo "$output"; exit 1; }
echo "PASS: Test 3"

echo
echo "All tests passed."
