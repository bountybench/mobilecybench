#!/usr/bin/env bash
# Integration test for build_apk.sh's local APK fingerprint cache.
#
# Runs build_apk.sh against a synthetic in-tmpdir project layout, mocking the
# heavy ops (Java/Android SDK, gradle, signing, codebase submodule) so the
# cache short-circuit logic can be exercised in seconds without an Android
# build environment.
#
# Exits 0 on success, non-zero on first failed assertion.

set -e
set -u
set -o pipefail

# Locate the real build_apk.sh and utils/ that ship with this checkout.
TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$TEST_DIR")"
SRC_BUILD_APK="$REPO_ROOT/build_apk.sh"
SRC_UTILS_DIR="$REPO_ROOT/utils"

[ -f "$SRC_BUILD_APK" ] || { echo "FAIL: source build_apk.sh not found at $SRC_BUILD_APK"; exit 1; }
[ -d "$SRC_UTILS_DIR" ] || { echo "FAIL: source utils/ not found at $SRC_UTILS_DIR"; exit 1; }

# Build a self-contained throwaway project layout.
TMP="$(mktemp -d -t build_apk_cache_test.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

cp "$SRC_BUILD_APK" "$TMP/build_apk.sh"
mkdir -p "$TMP/utils"
cp "$SRC_UTILS_DIR"/*.sh "$TMP/utils/"

mkdir -p "$TMP/apps/fake_app/codebase"

cat > "$TMP/apps/fake_app/metadata.json" <<'EOF'
{
  "package_name": "test.fake_app",
  "gh_link": "https://example.com/fake_app",
  "commit_version": "abc1234",
  "sdk": "35",
  "java": "17"
}
EOF

cat > "$TMP/apps/fake_app/build.sh" <<'EOF'
#!/bin/bash
# Fake per-app build: just produce an empty unsigned.apk where build_apk.sh expects it.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "[fake build.sh] producing $SCRIPT_DIR/unsigned.apk"
echo "fake-apk-content-$(date +%s%N)" > "$SCRIPT_DIR/unsigned.apk"
EOF
chmod +x "$TMP/apps/fake_app/build.sh"

# Initialize the codebase as a tiny git repo with the metadata's commit pinned to a tag.
(
    cd "$TMP/apps/fake_app/codebase"
    git init -q
    git -c user.email=t@t -c user.name=t commit -q --allow-empty -m initial
    git tag abc1234
)

# A wrapper that sources build_apk.sh, neutralizes the heavy ops, then runs main.
cat > "$TMP/run_build_with_mocks.sh" <<'EOF'
#!/bin/bash
set -e
WRAPPER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$WRAPPER_DIR/build_apk.sh"

# Override heavy ops with no-ops/cheap variants. Order matters: must come AFTER
# source so they shadow the originals before main() invokes them.
setup_java()                    { :; }
setup_android()                 { :; }
checkout_commit()               { :; }
check_submodule_initialized()   { :; }
sign_apk() {
    local in="$1" out="$2"
    mkdir -p "$(dirname "$out")"
    cp "$in" "$out"
    echo "[mock-sign] $in -> $out"
}

main "$@"
EOF
chmod +x "$TMP/run_build_with_mocks.sh"

# --- assertions ---

PASS_COUNT=0
FAIL_COUNT=0
fail() { echo "FAIL: $*"; FAIL_COUNT=$((FAIL_COUNT+1)); return 1; }
pass() { echo "PASS: $*"; PASS_COUNT=$((PASS_COUNT+1)); }

run_build() {
    # Captures stdout for grep assertions
    "$TMP/run_build_with_mocks.sh" "$@" 2>&1
}

APK_PATH="$TMP/apps/fake_app/apk/fake_app.apk"
FP_PATH="$TMP/apps/fake_app/apk/.fingerprint"

# 1. Default behavior: NO cache, no fingerprint written, build always runs.
echo
echo "=== Test 1: default (no --cache) does NOT touch the cache ==="
out=$(run_build fake_app)
echo "$out" | tail -5
[ -f "$APK_PATH" ] || fail "expected APK at $APK_PATH after default build"
[ -f "$FP_PATH" ] && fail "default build should NOT write fingerprint at $FP_PATH"
echo "$out" | grep -q "fake build.sh" || fail "default build should run fake build.sh"
if echo "$out" | grep -qE "Cache (HIT|MISS|.*saved)"; then
    fail "default build should produce no Cache HIT/MISS/saved messages"
fi
pass "default: build ran, no fingerprint side-effect"

# 2. First --cache build: cache MISS (no fingerprint exists), build runs, fingerprint saved.
echo
echo "=== Test 2: first --cache build populates cache ==="
out=$(run_build fake_app --cache)
echo "$out" | tail -10
[ -f "$APK_PATH" ] || fail "expected APK at $APK_PATH after --cache build"
[ -f "$FP_PATH" ] || fail "expected fingerprint at $FP_PATH after --cache build"
echo "$out" | grep -q "Cache MISS: no fingerprint" || fail "expected 'Cache MISS: no fingerprint' on first --cache"
echo "$out" | grep -q "fake build.sh" || fail "expected fake build.sh to run on first --cache"
echo "$out" | grep -q "Saved cache fingerprint" || fail "expected 'Saved cache fingerprint' on first --cache"
pass "first --cache: APK + fingerprint produced, cache MISS path taken"

FP1=$(cat "$FP_PATH")
APK1_MTIME=$(stat -f %m "$APK_PATH" 2>/dev/null || stat -c %Y "$APK_PATH")
echo "first --cache build fingerprint=$FP1, apk mtime=$APK1_MTIME"

# 3. Second --cache build with no input change: cache HIT, build SKIPPED.
echo
echo "=== Test 3: rerun --cache with no input change hits cache ==="
sleep 1  # ensure mtime would change if rebuilt
out=$(run_build fake_app --cache)
echo "$out" | tail -10
echo "$out" | grep -q "Cache HIT" || fail "expected 'Cache HIT' on rerun"
if echo "$out" | grep -q "fake build.sh"; then
    fail "fake build.sh should NOT run on cache hit"
fi
APK2_MTIME=$(stat -f %m "$APK_PATH" 2>/dev/null || stat -c %Y "$APK_PATH")
[ "$APK1_MTIME" = "$APK2_MTIME" ] || fail "APK mtime changed despite cache hit ($APK1_MTIME -> $APK2_MTIME)"
pass "second --cache: cache HIT, build skipped, APK untouched"

# 4. Touch a fingerprint input file: cache MISS, rebuild.
echo
echo "=== Test 4: changing build.sh invalidates cache ==="
echo "# trivial change for cache invalidation test" >> "$TMP/apps/fake_app/build.sh"
out=$(run_build fake_app --cache)
echo "$out" | tail -10
echo "$out" | grep -q "Cache MISS: build inputs changed" || fail "expected 'Cache MISS: build inputs changed' after build.sh edit"
echo "$out" | grep -q "fake build.sh" || fail "expected fake build.sh to run after invalidation"
FP2=$(cat "$FP_PATH")
[ "$FP1" != "$FP2" ] || fail "fingerprint should have changed (was $FP1, still $FP2)"
pass "fourth: input change invalidated cache, rebuilt, new fingerprint saved"

# 5. Drop --cache: build runs unconditionally, ignoring fingerprint.
echo
echo "=== Test 5: dropping --cache forces a rebuild even with valid fingerprint ==="
out=$(run_build fake_app)
echo "$out" | tail -10
if echo "$out" | grep -q "Cache HIT"; then
    fail "build without --cache should not consult the cache"
fi
echo "$out" | grep -q "fake build.sh" || fail "build without --cache should run"
pass "fifth: dropping --cache rebuilds, fingerprint ignored"

# 6. --cache + --commit override: cache logic skipped entirely.
echo
echo "=== Test 6: --cache + --commit skips cache logic ==="
out=$(run_build fake_app --cache --commit abc1234)
echo "$out" | tail -10
if echo "$out" | grep -qE "Cache HIT|Cache MISS"; then
    fail "--commit should bypass cache check entirely (no Cache HIT/MISS messages expected)"
fi
echo "$out" | grep -q "fake build.sh" || fail "--commit should still run the build"
pass "sixth: --commit bypassed cache, build ran"

# 7. --cache + --output override: cache logic skipped entirely.
echo
echo "=== Test 7: --cache + --output skips cache logic ==="
out=$(run_build fake_app --cache --output "$TMP/custom_out")
echo "$out" | tail -10
if echo "$out" | grep -qE "Cache HIT|Cache MISS"; then
    fail "--output should bypass cache check entirely"
fi
[ -f "$TMP/custom_out/fake_app.apk" ] || fail "expected APK at custom output path"
pass "seventh: --output bypassed cache, APK at custom path"

# 7b. External mutation of apk/<app>.apk forces a MISS (catches download_apk.py,
#     manual cp, etc. overwriting the cached APK).
echo
echo "=== Test 7b: external mutation of cached APK forces MISS ==="
# Re-populate the cache from a clean state (we destroyed the apk/ contents
# in test 6 by running --output to a different dir).
out=$(run_build fake_app --cache)
echo "$out" | grep -qE "Cache (HIT|saved fingerprint|MISS:)" || fail "expected cache activity on re-population"
[ -f "$APK_PATH" ] || fail "expected APK at $APK_PATH after repopulation"
[ -f "$FP_PATH" ] || fail "expected fingerprint at $FP_PATH after repopulation"

# Simulate something else (e.g. download_apk.py) overwriting the APK.
echo "downloaded-content-$(date +%s%N)" > "$APK_PATH"

out=$(run_build fake_app --cache)
echo "$out" | tail -10
echo "$out" | grep -q "Cache MISS: APK on disk doesn't match" \
    || fail "expected 'APK on disk doesn't match' MISS after external overwrite"
echo "$out" | grep -q "fake build.sh" || fail "expected rebuild after external overwrite"
pass "7b: external mutation of APK detected, cache fell through to rebuild"

# 8. --vuln + --cache: separate cache namespace under apk/<vuln_id>/, vuln.patch contributes to fingerprint.
echo
echo "=== Test 8: --cache --vuln has its own cache key ==="
mkdir -p "$TMP/apps/fake_app/synthetic_vulnerabilities/vuln_0/exploit_files"
mkdir -p "$TMP/apps/fake_app/synthetic_vulnerabilities/vuln_0/verify_files"
echo "# fake patch v1" > "$TMP/apps/fake_app/synthetic_vulnerabilities/vuln_0/vulnerability.patch"
echo "# noop" > "$TMP/apps/fake_app/synthetic_vulnerabilities/vuln_0/exploit_files/exploit.sh"
echo "# noop" > "$TMP/apps/fake_app/synthetic_vulnerabilities/vuln_0/verify_files/verify_exploit.sh"
echo '{"attacker_model":"remote_attacker"}' > "$TMP/apps/fake_app/synthetic_vulnerabilities/vuln_0/metadata.json"

# Mock apply_patch since we don't need a real git apply for the cache test.
cat > "$TMP/run_vuln_with_mocks.sh" <<'EOF'
#!/bin/bash
set -e
WRAPPER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$WRAPPER_DIR/build_apk.sh"
setup_java()                    { :; }
setup_android()                 { :; }
checkout_commit()               { :; }
check_submodule_initialized()   { :; }
apply_patch()                   { :; }
apply_vulnerability_patch()     { :; }
sign_apk() {
    local in="$1" out="$2"
    mkdir -p "$(dirname "$out")"
    cp "$in" "$out"
}
main "$@"
EOF
chmod +x "$TMP/run_vuln_with_mocks.sh"

out=$("$TMP/run_vuln_with_mocks.sh" fake_app --vuln vuln_0 --cache 2>&1)
echo "$out" | tail -10
VULN_APK="$TMP/apps/fake_app/apk/vuln_0/fake_app.apk"
VULN_FP="$TMP/apps/fake_app/apk/vuln_0/.fingerprint"
[ -f "$VULN_APK" ] || fail "expected vuln APK at $VULN_APK"
[ -f "$VULN_FP" ] || fail "expected vuln fingerprint at $VULN_FP"
echo "$out" | grep -q "Cache MISS: no fingerprint" || fail "expected MISS on first --cache --vuln build"

VULN_FP1=$(cat "$VULN_FP")
[ "$VULN_FP1" != "$FP2" ] || fail "vuln fingerprint should differ from clean fingerprint (got same: $VULN_FP1)"
pass "eighth: --cache --vuln: separate cache key, fingerprint distinct from clean"

# 9. Re-run --cache --vuln: cache HIT.
echo
echo "=== Test 9: rerun --cache --vuln hits its own cache ==="
out=$("$TMP/run_vuln_with_mocks.sh" fake_app --vuln vuln_0 --cache 2>&1)
echo "$out" | tail -10
echo "$out" | grep -q "Cache HIT" || fail "expected vuln Cache HIT on rerun"
pass "ninth: --cache --vuln rerun hits cache"

# 10. Touch vulnerability.patch: vuln cache invalidates, clean cache untouched.
echo
echo "=== Test 10: editing vulnerability.patch invalidates only the vuln cache ==="
echo "# fake patch v2" > "$TMP/apps/fake_app/synthetic_vulnerabilities/vuln_0/vulnerability.patch"
out=$("$TMP/run_vuln_with_mocks.sh" fake_app --vuln vuln_0 --cache 2>&1)
echo "$out" | grep -q "Cache MISS: build inputs changed" || fail "expected vuln Cache MISS after patch edit"
VULN_FP2=$(cat "$VULN_FP")
[ "$VULN_FP1" != "$VULN_FP2" ] || fail "vuln fingerprint should have changed"

# Clean cache should NOT be invalidated by patch edit (patch isn't in clean fingerprint).
out=$(run_build fake_app --cache)
echo "$out" | grep -q "Cache HIT" || fail "clean cache should still hit after vuln patch edit"
pass "tenth: vuln cache invalidated, clean cache untouched"

echo
echo "=========================================="
echo "PASS: $PASS_COUNT   FAIL: $FAIL_COUNT"
echo "=========================================="
[ "$FAIL_COUNT" = "0" ]
