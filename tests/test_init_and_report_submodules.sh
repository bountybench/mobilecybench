#!/usr/bin/env bash
# Integration test for init_and_report_submodules.sh.
#
# Validates that:
#   1. With no args, all non-zerodays submodules are inited + reported.
#   2. With a path arg, only that path is inited and reported.
#   3. A path arg that's a parent of a submodule path also matches
#      (e.g. `apps/foo` matches `apps/foo/codebase`).
#   4. Failure of an unrelated submodule does not abort the script when
#      the user scoped to a working submodule path.
#   5. Passing zerodays explicitly still initializes/reports zerodays.
#
# Mocks `git submodule` via PATH override so we exercise the script's
# argument-passing without needing real submodule remotes.

set -euo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$TEST_DIR")"
SRC_SCRIPT="$REPO_ROOT/init_and_report_submodules.sh"
[ -f "$SRC_SCRIPT" ] || { echo "FAIL: source init_and_report_submodules.sh not found at $SRC_SCRIPT"; exit 1; }

TMP="$(mktemp -d -t init_submodules_test.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

# Synthetic project layout. `foo` has TWO submodules (mirrors real-world
# apps that ship both `codebase` and `<app>-docker`, e.g. jitsi-meet).
mkdir -p "$TMP/apps/foo/codebase" "$TMP/apps/foo/foo-docker" \
         "$TMP/apps/bar/codebase" "$TMP/apps/wordpress/codebase" \
         "$TMP/zerodays"
echo "f1" > "$TMP/apps/foo/codebase/file.txt"
echo "f2" > "$TMP/apps/foo/foo-docker/file.txt"
echo "b"  > "$TMP/apps/bar/codebase/file.txt"
echo "w"  > "$TMP/apps/wordpress/codebase/file.txt"
echo "z"  > "$TMP/zerodays/file.txt"

# .gitmodules so `git config --file .gitmodules` enumerates them.
cat > "$TMP/.gitmodules" <<'EOF'
[submodule "apps/foo/codebase"]
	path = apps/foo/codebase
	url = https://example.invalid/foo
[submodule "apps/foo/foo-docker"]
	path = apps/foo/foo-docker
	url = https://example.invalid/foo-docker
[submodule "apps/bar/codebase"]
	path = apps/bar/codebase
	url = https://example.invalid/bar
[submodule "apps/wordpress/codebase"]
	path = apps/wordpress/codebase
	url = https://example.invalid/wordpress
[submodule "zerodays"]
	path = zerodays
	url = https://example.invalid/zerodays
EOF

# Bring the script under test into the tmp dir.
cp "$SRC_SCRIPT" "$TMP/init_and_report_submodules.sh"

# Mock `git`. We only intercept `submodule init` and `submodule update`;
# pass `git config --file .gitmodules ...` through to real git so the
# script can enumerate paths.
cat > "$TMP/git" <<MOCK
#!/usr/bin/env bash
# Argument list of every invocation captured for assertions.
echo "git \$*" >> "$TMP/git_calls.log"
case "\$1" in
    submodule)
        # submodule init [paths...] | submodule update [...] [paths...]
        # We just succeed; the real submodule contents already exist on disk.
        if [[ "\$2" == "init" ]]; then
            shift 2
            echo "[mock] git submodule init \$*"
            # Simulate: if "apps/wordpress/codebase" is among the args,
            # leave a marker so we can later test the failure path; for
            # success path tests we don't fail here.
            : "\${MOCK_FAIL_WORDPRESS:=0}"
            for p in "\$@"; do
                if [[ "\$p" == "apps/wordpress/codebase" && "\$MOCK_FAIL_WORDPRESS" == "1" ]]; then
                    echo "Failed to clone 'apps/wordpress/codebase' a second time, aborting" >&2
                    exit 1
                fi
            done
            exit 0
        elif [[ "\$2" == "update" ]]; then
            shift 2
            echo "[mock] git submodule update \$*"
            for p in "\$@"; do
                if [[ "\$p" == "apps/wordpress/codebase" && "\${MOCK_FAIL_WORDPRESS:-0}" == "1" ]]; then
                    echo "Failed to clone 'apps/wordpress/codebase' a second time, aborting" >&2
                    exit 1
                fi
            done
            exit 0
        fi
        ;;
    config)
        # Pass through to real git for .gitmodules enumeration.
        shift
        exec /usr/bin/env -i PATH="/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin" git config "\$@"
        ;;
esac
echo "[mock] unhandled: git \$*" >&2
exit 99
MOCK
chmod +x "$TMP/git"

cd "$TMP"
PATH="$TMP:$PATH"
export PATH

assert_eq() {
    local label="$1" expected="$2" actual="$3"
    if [[ "$expected" != "$actual" ]]; then
        echo "FAIL: $label"
        echo "  expected: $expected"
        echo "  actual:   $actual"
        exit 1
    fi
    echo "PASS: $label"
}

assert_grep() {
    local label="$1" pattern="$2" file="$3"
    if ! grep -q -- "$pattern" "$file"; then
        echo "FAIL: $label (pattern '$pattern' not in $file)"
        echo "--- file contents ---"
        cat "$file"
        exit 1
    fi
    echo "PASS: $label"
}

# =====================================================================
# Test 1: no args — inits & reports all submodules except zerodays
# =====================================================================
rm -f git_calls.log submodule_size_report.txt
bash ./init_and_report_submodules.sh > /dev/null
[ -f git_calls.log ] || { echo "FAIL: no git calls captured"; exit 1; }
# Init/update should be scoped to every registered path except zerodays.
assert_grep "Test 1: init called without zerodays" "^git submodule init apps/foo/codebase apps/foo/foo-docker apps/bar/codebase apps/wordpress/codebase$" git_calls.log
assert_grep "Test 1: update called without zerodays" "^git submodule update --recursive --progress apps/foo/codebase apps/foo/foo-docker apps/bar/codebase apps/wordpress/codebase$" git_calls.log
# Report should mention four app submodules (foo has codebase + foo-docker).
assert_grep "Test 1: report includes foo/codebase"   "Submodule: apps/foo/codebase"       submodule_size_report.txt
assert_grep "Test 1: report includes foo/foo-docker" "Submodule: apps/foo/foo-docker"     submodule_size_report.txt
assert_grep "Test 1: report includes bar"            "Submodule: apps/bar/codebase"       submodule_size_report.txt
assert_grep "Test 1: report includes wordpress"      "Submodule: apps/wordpress/codebase" submodule_size_report.txt
if grep -q "Submodule: zerodays" submodule_size_report.txt; then
    echo "FAIL: Test 1 — report should not include zerodays by default"; exit 1
fi
echo "PASS: Test 1: report excludes zerodays by default"
assert_grep "Test 1: count is 4"                     "Submodules/App Count: 4"            submodule_size_report.txt

# =====================================================================
# Test 2: one path arg — scopes init AND report to that path
# =====================================================================
rm -f git_calls.log submodule_size_report.txt
bash ./init_and_report_submodules.sh apps/foo/codebase > /dev/null
assert_grep "Test 2: init called WITH foo path"   "^git submodule init apps/foo/codebase$"   git_calls.log
assert_grep "Test 2: update called WITH foo path" "^git submodule update --recursive --progress apps/foo/codebase$" git_calls.log
assert_grep "Test 2: report includes foo"         "Submodule: apps/foo/codebase" submodule_size_report.txt
if grep -q "Submodule: apps/bar/codebase" submodule_size_report.txt; then
    echo "FAIL: Test 2 — report should not include bar when scoped to foo"; exit 1
fi
echo "PASS: Test 2: report excludes bar when scoped"
assert_grep "Test 2: count is 1"                  "Submodules/App Count: 1"      submodule_size_report.txt

# =====================================================================
# Test 3: parent path arg matches ALL descendant submodules
#         (real apps like jitsi-meet ship `codebase` AND `<app>-docker`,
#         so `apps/jitsi-meet` must scope to BOTH submodules.)
# =====================================================================
rm -f git_calls.log submodule_size_report.txt
bash ./init_and_report_submodules.sh apps/foo > /dev/null
assert_grep "Test 3: report includes foo/codebase" \
    "Submodule: apps/foo/codebase" submodule_size_report.txt
assert_grep "Test 3: report includes foo/foo-docker (sibling submodule)" \
    "Submodule: apps/foo/foo-docker" submodule_size_report.txt
if grep -q "Submodule: apps/bar/codebase" submodule_size_report.txt; then
    echo "FAIL: Test 3 — report should not include bar when scoped to apps/foo"; exit 1
fi
echo "PASS: Test 3: report excludes apps/bar when scoped to apps/foo"
assert_grep "Test 3: count is 2 (both foo submodules)" \
    "Submodules/App Count: 2" submodule_size_report.txt
# Also assert init/update were called with the parent path passed through to git.
assert_grep "Test 3: init called WITH apps/foo" \
    "^git submodule init apps/foo$" git_calls.log
assert_grep "Test 3: update called WITH apps/foo" \
    "^git submodule update --recursive --progress apps/foo$" git_calls.log

# =====================================================================
# Test 4: scoped to working submodule does NOT trigger unrelated failures
# =====================================================================
rm -f git_calls.log submodule_size_report.txt
# Mock will fail on wordpress IF wordpress is in args. Run scoped to foo.
MOCK_FAIL_WORDPRESS=1 bash ./init_and_report_submodules.sh apps/foo/codebase > /dev/null
assert_grep "Test 4: foo init succeeded under wordpress-fail mode" \
    "Submodule: apps/foo/codebase" submodule_size_report.txt

# Conversely: if no path arg given AND wordpress would fail, the script
# should fail because the default path list includes wordpress.
if MOCK_FAIL_WORDPRESS=1 bash ./init_and_report_submodules.sh > /dev/null 2>&1; then
    echo "FAIL: Test 4 — default init should fail when an included submodule fails"; exit 1
fi
echo "PASS: Test 4: default init still fails on included broken submodule"

# =====================================================================
# Test 5: zerodays can still be initialized/reported when explicit
# =====================================================================
rm -f git_calls.log submodule_size_report.txt
bash ./init_and_report_submodules.sh zerodays > /dev/null
assert_grep "Test 5: init called WITH zerodays" \
    "^git submodule init zerodays$" git_calls.log
assert_grep "Test 5: update called WITH zerodays" \
    "^git submodule update --recursive --progress zerodays$" git_calls.log
assert_grep "Test 5: report includes zerodays when explicit" \
    "Submodule: zerodays" submodule_size_report.txt
assert_grep "Test 5: count is 1" "Submodules/App Count: 1" submodule_size_report.txt

echo
echo "All tests passed."
