#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODEBASE_DIR="$SCRIPT_DIR/codebase"
PATCH_FILE="$SCRIPT_DIR/local-sdk.patch"
SDK_REPO_DIR="${TMPDIR:-/tmp}/mobilecybench-bitwarden-sdk-internal"
SDK_COMMIT="f43bbc685c747c7362e23bae87b1a4977aea4f05"
SDK_KOTLIN_DIR="$SDK_REPO_DIR/crates/bitwarden-uniffi/kotlin"
LOCAL_SDK_AAR="$HOME/.m2/repository/com/bitwarden/sdk-android-temp/LOCAL/sdk-android-temp-LOCAL.aar"

GRADLE_TASKS=(
    :app:assembleFdroidRelease
    -x lintVitalFdroidRelease
    -x lintVitalAnalyzeFdroidRelease
    -x lintVitalReportFdroidRelease
    -x generateFdroidReleaseLintVitalReportModel
    -x lintVitalAnalyzeRelease
    -x generateReleaseLintVitalModel
    --no-daemon
)

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

prepare_sdk_repo() {
    if [ ! -d "$SDK_REPO_DIR/.git" ]; then
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
}

prepare_bitwarden_codebase() {
    if ! git -C "$CODEBASE_DIR" apply --check "$PATCH_FILE"; then
        echo "[ERROR] Bitwarden local SDK patch no longer applies cleanly."
        exit 1
    fi
    git -C "$CODEBASE_DIR" apply "$PATCH_FILE"

    cat > "$CODEBASE_DIR/user.properties" <<'EOF'
localSdk=true
EOF
}

cd "$CODEBASE_DIR"

echo "=== Building Bitwarden (FdroidRelease) ==="

ensure_rust_toolchain
prepare_sdk_repo

if [ ! -f "$LOCAL_SDK_AAR" ]; then
    echo "[INFO] Building and publishing local Bitwarden SDK..."
    build_local_sdk
else
    echo "[INFO] Reusing local Bitwarden SDK from Maven cache."
fi

prepare_bitwarden_codebase

./gradlew "${GRADLE_TASKS[@]}"

if [ -f "app/build/outputs/apk/fdroid/release/app-fdroid-release-unsigned.apk" ]; then
    cp app/build/outputs/apk/fdroid/release/app-fdroid-release-unsigned.apk "$SCRIPT_DIR/unsigned.apk"
else
    cp app/build/outputs/apk/fdroid/release/app-fdroid-release.apk "$SCRIPT_DIR/unsigned.apk"
fi

echo "=== Bitwarden Build Finished ==="
