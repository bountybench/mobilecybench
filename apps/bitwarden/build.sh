#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODEBASE_DIR="$SCRIPT_DIR/codebase"
LOCAL_SDK_PATCH="$SCRIPT_DIR/local-sdk.patch"
FAST_RELEASE_PATCH="$SCRIPT_DIR/fast-release.patch"
SDK_REPO_DIR="${TMPDIR:-/tmp}/mobilecybench-bitwarden-sdk-internal"
SDK_COMMIT="f43bbc685c747c7362e23bae87b1a4977aea4f05"
SDK_KOTLIN_DIR="$SDK_REPO_DIR/crates/bitwarden-uniffi/kotlin"
LOCAL_SDK_AAR="$HOME/.m2/repository/com/bitwarden/sdk-android-temp/LOCAL/sdk-android-temp-LOCAL.aar"
LOCAL_SDK_STAMP="$HOME/.m2/repository/com/bitwarden/sdk-android-temp/LOCAL/sdk-android-temp-LOCAL.stamp"
BUILD_LOG="$(mktemp /tmp/bitwarden-build.XXXXXX.log)"
BW_FAST_RELEASE="${BW_FAST_RELEASE:-true}"

GRADLE_TASKS=(
    :app:assembleFdroidRelease
    --no-daemon
    --max-workers=2
    --console=plain
    -x lintVitalFdroidRelease
    -x lintVitalAnalyzeFdroidRelease
    -x lintVitalReportFdroidRelease
    -x generateFdroidReleaseLintVitalReportModel
    -x lintVitalAnalyzeRelease
    -x generateReleaseLintVitalModel
    "-Pbw.fastRelease=$BW_FAST_RELEASE"
)

cleanup() {
    rm -f "$BUILD_LOG"
}

trap cleanup EXIT

ensure_rust_toolchain() {
    if [ -f "$HOME/.cargo/env" ]; then
        # shellcheck disable=SC1090
        source "$HOME/.cargo/env"
    fi

    if ! command -v cargo >/dev/null 2>&1; then
        curl https://sh.rustup.rs -sSf | sh -s -- -y --profile minimal --no-modify-path
        # shellcheck disable=SC1090
        source "$HOME/.cargo/env"
    fi
}

file_digest() {
    shasum -a 256 "$1" | awk '{print $1}'
}

local_sdk_stamp() {
    printf '%s %s %s\n' \
        "$SDK_COMMIT" \
        "$(file_digest "$LOCAL_SDK_PATCH")" \
        "$(file_digest "$FAST_RELEASE_PATCH")"
}

local_sdk_is_fresh() {
    [ -f "$LOCAL_SDK_AAR" ] && [ -f "$LOCAL_SDK_STAMP" ] && [ "$(cat "$LOCAL_SDK_STAMP")" = "$(local_sdk_stamp)" ]
}

write_local_sdk_stamp() {
    mkdir -p "$(dirname "$LOCAL_SDK_STAMP")"
    local_sdk_stamp > "$LOCAL_SDK_STAMP"
}

prepare_sdk_repo() {
    if [ ! -d "$SDK_REPO_DIR/.git" ] || ! git -C "$SDK_REPO_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        rm -rf "$SDK_REPO_DIR"
        git clone https://github.com/bitwarden/sdk-internal.git "$SDK_REPO_DIR"
    fi

    git -C "$SDK_REPO_DIR" fetch --tags origin
    git -C "$SDK_REPO_DIR" reset --hard HEAD
    git -C "$SDK_REPO_DIR" clean -fdx
    git -C "$SDK_REPO_DIR" checkout "$SDK_COMMIT"
}

build_local_sdk() {
    local ndk_root="${ANDROID_HOME:-}/ndk"
    local ndk_dir
    local toolchain_version
    local host_triple
    local linker_bin

    ndk_dir="$(find "$ndk_root" -mindepth 1 -maxdepth 1 -type d | sort -V | tail -n 1)"
    if [ -z "$ndk_dir" ]; then
        echo "[ERROR] Android NDK not found under $ndk_root"
        exit 1
    fi

    toolchain_version="$(sed -n 's/^channel = "\(.*\)"/\1/p' "$SDK_REPO_DIR/rust-toolchain.toml" | head -n 1)"
    host_triple="$(rustc -vV | sed -n 's/^host: //p')"
    rustup toolchain install "${toolchain_version}-${host_triple}" --profile minimal >/dev/null 2>&1 || true
    rustup target add --toolchain "${toolchain_version}-${host_triple}" x86_64-linux-android >/dev/null 2>&1 || true

    linker_bin="$(find "$ndk_dir/toolchains/llvm/prebuilt" -path '*/bin/x86_64-linux-android28-clang' | head -n 1)"
    if [ -z "$linker_bin" ]; then
        echo "[ERROR] Android x86_64 clang linker not found in $ndk_dir"
        exit 1
    fi

    export ANDROID_NDK_HOME="$ndk_dir"
    export CC_x86_64_linux_android="$linker_bin"
    export CARGO_TARGET_X86_64_LINUX_ANDROID_LINKER="$linker_bin"
    export AR_x86_64_linux_android="$(dirname "$linker_bin")/llvm-ar"

    mkdir -p "$SDK_KOTLIN_DIR/sdk/src/main/jniLibs/x86_64"
    (
        cd "$SDK_REPO_DIR"
        cargo build -p bitwarden-uniffi --release --target=x86_64-linux-android
    )
    cp "$SDK_REPO_DIR/target/x86_64-linux-android/release/libbitwarden_uniffi.so" \
        "$SDK_KOTLIN_DIR/sdk/src/main/jniLibs/x86_64/libbitwarden_uniffi.so"

    (
        cd "$SDK_REPO_DIR"
        cargo run -p uniffi-bindgen generate \
            "$SDK_KOTLIN_DIR/sdk/src/main/jniLibs/x86_64/libbitwarden_uniffi.so" \
            --library \
            --language kotlin \
            --no-format \
            --out-dir "$SDK_KOTLIN_DIR/sdk/src/main/java"
    )

    (
        cd "$SDK_KOTLIN_DIR"
        ./gradlew sdk:publishToMavenLocal -Pversion=LOCAL --no-daemon
    )

    write_local_sdk_stamp
}

prepare_bitwarden_codebase() {
    apply_patch_once "$LOCAL_SDK_PATCH"
    apply_patch_once "$FAST_RELEASE_PATCH"

    cat > "$CODEBASE_DIR/user.properties" <<'EOF'
localSdk=true
EOF
}

apply_patch_once() {
    local patch_file="$1"

    if git -C "$CODEBASE_DIR" apply --reverse --check "$patch_file" >/dev/null 2>&1; then
        echo "[INFO] Patch already present: $(basename "$patch_file")"
        return
    fi

    if ! git -C "$CODEBASE_DIR" apply --check "$patch_file"; then
        echo "[ERROR] Patch no longer applies cleanly: $(basename "$patch_file")"
        exit 1
    fi
    git -C "$CODEBASE_DIR" apply "$patch_file"
}

cd "$CODEBASE_DIR"

echo "=== Building Bitwarden (FdroidRelease) ==="

ensure_rust_toolchain
prepare_sdk_repo

if ! local_sdk_is_fresh; then
    echo "[INFO] Building and publishing local Bitwarden SDK..."
    build_local_sdk
else
    echo "[INFO] Reusing local Bitwarden SDK from Maven cache."
fi

prepare_bitwarden_codebase

set +e
start_ts="$(date +%s)"
./gradlew "${GRADLE_TASKS[@]}" >"$BUILD_LOG" 2>&1 &
gradle_pid=$!

while kill -0 "$gradle_pid" 2>/dev/null; do
    sleep 60
    elapsed="$(( $(date +%s) - start_ts ))"
    echo "[INFO] Bitwarden Gradle build in progress (${elapsed}s elapsed). Last 5 log lines:"
    tail -n 5 "$BUILD_LOG"
done

wait "$gradle_pid"
gradle_status=$?
set -e

if [ "$gradle_status" -ne 0 ]; then
    echo "[ERROR] Bitwarden Gradle build failed. Last 200 log lines:"
    tail -n 200 "$BUILD_LOG"
    exit "$gradle_status"
fi

APK_PATH="$(find app/build/outputs/apk -type f -path '*/fdroid/release/*.apk' | head -n 1)"
if [ -z "$APK_PATH" ]; then
    echo "[ERROR] Bitwarden APK not found under app/build/outputs/apk"
    find app/build/outputs -maxdepth 4 -type f | sort
    exit 1
fi

cp "$APK_PATH" "$SCRIPT_DIR/unsigned.apk"

echo "=== Bitwarden Build Finished ==="
