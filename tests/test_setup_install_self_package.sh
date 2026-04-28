#!/usr/bin/env bash
# Unit test for setup.sh's install_self_package function.
#
# Validates the install path picks the right pip across:
#   1. Active venv ($VIRTUAL_ENV set + venv pip exists) → uses venv pip.
#   2. No venv set (CI / Linux without venv) → uses $PYTHON -m pip.
#   3. $VIRTUAL_ENV set but pip missing (broken venv) → falls back to $PYTHON -m pip.
#   4. $VIRTUAL_ENV set but PATH does NOT include venv (subprocess inheriting
#      non-activated PATH) → still uses venv pip via the absolute path.
#
# We extract the function from setup.sh and invoke it standalone with mock
# pip/python implementations that just record their arguments.

set -euo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$TEST_DIR")"
SETUP_SCRIPT="$REPO_ROOT/setup.sh"
[ -f "$SETUP_SCRIPT" ] || { echo "FAIL: source setup.sh not found"; exit 1; }

TMP="$(mktemp -d -t setup_install_self_test.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

# Extract just the install_self_package function (so we can call it
# without sourcing all of setup.sh, which has side effects on import).
awk '/^install_self_package\(\) \{/,/^\}/' "$SETUP_SCRIPT" > "$TMP/fn.sh"
[ -s "$TMP/fn.sh" ] || { echo "FAIL: could not extract install_self_package"; exit 1; }

# Mock pip/python. Each writes its argv to a logfile named after itself.
make_mock() {
    local name="$1" path="$2"
    cat > "$path" <<MOCK
#!/usr/bin/env bash
echo "[$name] \$*" >> "$TMP/calls.log"
exit 0
MOCK
    chmod +x "$path"
}

# Build a fake "venv" with its own pip
mkdir -p "$TMP/fake_venv/bin"
make_mock "venv-pip" "$TMP/fake_venv/bin/pip"

# A "system" python that records as $PYTHON -m pip
make_mock "system-python" "$TMP/system_python"

# Runner: invokes the install function with controlled env.
run_install() {
    local label="$1" venv_var="$2" python_var="$3"
    rm -f "$TMP/calls.log"
    (
        # Source the function in a subshell to avoid contaminating our env.
        set +u  # the function uses ${VIRTUAL_ENV:-} so set -u inside is fine,
                # but the awk extract may not include it; loosen for safety.
        VIRTUAL_ENV="$venv_var"
        PYTHON="$python_var"
        export VIRTUAL_ENV PYTHON
        # shellcheck disable=SC1090
        source "$TMP/fn.sh"
        install_self_package
    )
    if [ -f "$TMP/calls.log" ]; then
        local actual
        actual=$(cat "$TMP/calls.log")
        echo "  [$label] -> $actual"
    fi
}

assert_contains() {
    local label="$1" expected_substring="$2" actual="$3"
    if [[ "$actual" != *"$expected_substring"* ]]; then
        echo "FAIL: $label"
        echo "  expected to contain: $expected_substring"
        echo "  actual: $actual"
        exit 1
    fi
    echo "PASS: $label"
}

# =====================================================================
# Test 1: active venv → uses venv pip
# =====================================================================
echo "Test 1: \$VIRTUAL_ENV set + venv pip exists"
rm -f "$TMP/calls.log"
(
    VIRTUAL_ENV="$TMP/fake_venv" PYTHON="$TMP/system_python"
    export VIRTUAL_ENV PYTHON
    source "$TMP/fn.sh"
    install_self_package
)
log=$(cat "$TMP/calls.log")
assert_contains "Test 1: invoked venv pip" "[venv-pip] install -e ." "$log"
[[ "$log" != *"[system-python]"* ]] || { echo "FAIL: Test 1 also called system python"; exit 1; }
echo "PASS: Test 1: did NOT also call system python"

# =====================================================================
# Test 2: no venv set → uses $PYTHON -m pip
# =====================================================================
echo
echo "Test 2: \$VIRTUAL_ENV unset"
rm -f "$TMP/calls.log"
(
    unset VIRTUAL_ENV
    PYTHON="$TMP/system_python"
    export PYTHON
    source "$TMP/fn.sh"
    install_self_package
)
log=$(cat "$TMP/calls.log")
assert_contains "Test 2: invoked \$PYTHON -m pip" "[system-python] -m pip install -e ." "$log"

# =====================================================================
# Test 3: $VIRTUAL_ENV set but pip is missing (broken venv)
# =====================================================================
echo
echo "Test 3: \$VIRTUAL_ENV set but venv/bin/pip missing"
mkdir -p "$TMP/broken_venv/bin"  # no pip in there
rm -f "$TMP/calls.log"
(
    VIRTUAL_ENV="$TMP/broken_venv" PYTHON="$TMP/system_python"
    export VIRTUAL_ENV PYTHON
    source "$TMP/fn.sh"
    install_self_package
)
log=$(cat "$TMP/calls.log")
assert_contains "Test 3: fell back to \$PYTHON -m pip" "[system-python] -m pip install -e ." "$log"

# =====================================================================
# Test 4: $VIRTUAL_ENV set, but PATH does NOT include venv —
# emulates a subprocess that inherited VIRTUAL_ENV without an activated PATH.
# =====================================================================
echo
echo "Test 4: \$VIRTUAL_ENV set, venv NOT on PATH"
rm -f "$TMP/calls.log"
(
    # Strip the test's TMP from PATH so bare `pip` doesn't resolve to a mock.
    VIRTUAL_ENV="$TMP/fake_venv" PYTHON="$TMP/system_python"
    PATH="/usr/bin:/bin"
    export VIRTUAL_ENV PYTHON PATH
    source "$TMP/fn.sh"
    install_self_package
)
log=$(cat "$TMP/calls.log")
assert_contains "Test 4: still uses venv pip via absolute path" "[venv-pip] install -e ." "$log"

echo
echo "All tests passed."
