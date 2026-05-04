#!/usr/bin/env bash
# Regression test for run_ci_local.sh app submodule initialization.
#
# Exercises checkout_commit() in a synthetic app with two submodules. The local
# CI runner must initialize every .gitmodules entry under the app (codebase plus
# auxiliary runtime submodules), while still resetting/checking out only codebase.

set -euo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$TEST_DIR")"
SRC_RUN_CI="$REPO_ROOT/run_ci_local.sh"
[ -f "$SRC_RUN_CI" ] || { echo "FAIL: source run_ci_local.sh not found at $SRC_RUN_CI"; exit 1; }

REAL_GIT="$(command -v git)"
TMP="$(mktemp -d -t run_ci_submodules_test.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/apps/foo/codebase" "$TMP/apps/foo/foo-docker" "$TMP/apps/bar/codebase"
cat > "$TMP/apps/foo/metadata.json" <<'JSON'
{"commit_version":"target123"}
JSON

cat > "$TMP/.gitmodules" <<'EOF_GITMODULES'
[submodule "apps/foo/codebase"]
	path = apps/foo/codebase
	url = https://example.invalid/foo-codebase
[submodule "apps/foo/foo-docker"]
	path = apps/foo/foo-docker
	url = https://example.invalid/foo-docker
[submodule "apps/bar/codebase"]
	path = apps/bar/codebase
	url = https://example.invalid/bar-codebase
EOF_GITMODULES

# Extract only the helper functions under test. Sourcing the full runner would
# execute local CI setup (Docker/emulator), so this test loads the function slice
# that includes current_app_dir(), init_app_submodules(), and
# checkout_commit().
awk '
    /^current_app_dir\(\)/ { capture = 1 }
    /^# Apply a vulnerability patch/ { capture = 0 }
    capture { print }
' "$SRC_RUN_CI" > "$TMP/run_ci_checkout_functions.sh"

cat > "$TMP/git" <<EOF_MOCK
#!/usr/bin/env bash
set -euo pipefail
printf 'git' >> "$TMP/git_calls.log"
for arg in "\$@"; do printf ' %q' "\$arg" >> "$TMP/git_calls.log"; done
printf '\n' >> "$TMP/git_calls.log"

while [[ "\${1:-}" == "-C" ]]; do
    cd "\$2"
    shift 2
done

case "\${1:-}" in
    rev-parse)
        if [[ "\${2:-}" == "--show-prefix" && "\$(pwd)" == "$TMP/apps/foo" ]]; then
            echo "apps/foo/"
            exit 0
        fi
        echo "mock git rev-parse only supports apps/foo --show-prefix" >&2
        exit 128
        ;;
    config)
        shift
        exec "$REAL_GIT" config "\$@"
        ;;
    submodule)
        if [[ "\${2:-}" == "update" && "\${3:-}" == "--init" && -n "\${4:-}" ]]; then
            echo "\$4" >> "$TMP/initialized_paths.log"
            exit 0
        fi
        ;;
    reset|clean|checkout)
        printf '%s|git' "\$(pwd)" >> "$TMP/codebase_ops.log"
        for arg in "\$@"; do printf ' %q' "\$arg" >> "$TMP/codebase_ops.log"; done
        printf '\n' >> "$TMP/codebase_ops.log"
        exit 0
        ;;
esac

echo "mock git: unhandled invocation: git \$*" >&2
exit 99
EOF_MOCK
chmod +x "$TMP/git"

PATH="$TMP:$PATH"
export PATH

(
    ROOT_DIR="$TMP"
    INFO="[INFO]"
    ERROR="[ERROR]"
    source "$TMP/run_ci_checkout_functions.sh"
    cd "$TMP/apps/foo"
    checkout_commit
) > "$TMP/stdout.log" 2> "$TMP/stderr.log"

assert_eq() {
    local label="$1" expected="$2" actual="$3"
    if [[ "$expected" != "$actual" ]]; then
        echo "FAIL: $label"
        echo "  expected: $expected"
        echo "  actual:   $actual"
        echo "--- stdout ---"
        cat "$TMP/stdout.log"
        echo "--- stderr ---"
        cat "$TMP/stderr.log"
        echo "--- git calls ---"
        cat "$TMP/git_calls.log"
        exit 1
    fi
    echo "PASS: $label"
}

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

expected_inits=$'apps/foo/codebase\napps/foo/foo-docker'
actual_inits="$(cat "$TMP/initialized_paths.log")"
assert_eq "checkout_commit initializes every submodule under apps/foo" "$expected_inits" "$actual_inits"

if grep -q 'apps/bar/codebase' "$TMP/initialized_paths.log"; then
    echo "FAIL: checkout_commit should not initialize sibling app submodules"
    exit 1
fi
echo "PASS: checkout_commit excludes sibling app submodules"

assert_grep "codebase reset happens inside codebase only" ".*/apps/foo/codebase\|git reset --hard HEAD" "$TMP/codebase_ops.log"
assert_grep "codebase clean happens inside codebase only" ".*/apps/foo/codebase\|git clean -fdx" "$TMP/codebase_ops.log"
assert_grep "codebase checkout uses metadata commit" ".*/apps/foo/codebase\|git checkout target123" "$TMP/codebase_ops.log"

if grep -Eq 'foo-docker\|git (reset|clean|checkout)' "$TMP/codebase_ops.log"; then
    echo "FAIL: auxiliary submodule must not be reset, cleaned, or checked out to the app commit"
    exit 1
fi
echo "PASS: auxiliary submodule is initialized but not reset/cleaned/checked out"

echo
cat "$TMP/stdout.log"
echo
printf 'All tests passed.\n'
