#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

LOG_PREFIX="[deltachat_setup_app_source]"
info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*"; }
error(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*"; exit 1; }

install_rust_targets() {
    if command -v rustup >/dev/null 2>&1; then
        RUSTUP_TOOLCHAIN="1.86.0"
        TARGETS="aarch64-linux-android"

        if ! rustup install "$RUSTUP_TOOLCHAIN"; then
            error "Failed to install toolchain $RUSTUP_TOOLCHAIN"
        fi

        if ! rustup target add $TARGETS --toolchain "$RUSTUP_TOOLCHAIN"; then
            error "Failed to install target $TARGETS"
        fi

        export CARGO_INCREMENTAL=1
        export CARGO_NET_RETRY=10
        export CARGO_HTTP_TIMEOUT=60
        export CARGO_HTTP_LOW_SPEED_LIMIT=10
    else
        error "rustup not found"
    fi
}

build_rust_core() {
    git submodule update --init --recursive
    ./scripts/ndk-make.sh arm64-v8a
}

build_deltachat() {
    export GRADLE_OPTS="$GRADLE_OPTS -Dorg.gradle.caching=true -Dorg.gradle.parallel=true -Dorg.gradle.configureondemand=true"

    local temp_out=$(mktemp)
    local temp_err=$(mktemp)

    if ./gradlew assembleFossRelease \
        --no-daemon \
        --parallel \
        --build-cache \
        --configure-on-demand \
        --max-workers=2 \
        -Dorg.gradle.jvmargs="-Xmx3g -XX:MaxMetaspaceSize=512m -XX:+UseParallelGC" \
        > "$temp_out" 2> "$temp_err"; then
        rm -f "$temp_out" "$temp_err"
    else
        local exit_code=$?
        error "Build failed with exit code $exit_code"

        if [[ -s "$temp_err" ]]; then
            cat "$temp_err"
        fi

        if [[ -s "$temp_out" ]]; then
            tail -50 "$temp_out"
        fi

        rm -f "$temp_out" "$temp_err"
        exit $exit_code
    fi
}

main() {
    METADATA_FILE="$SCRIPT_DIR/metadata.json"
    if [[ ! -f "$METADATA_FILE" ]]; then
        error "metadata.json not found"
    fi

    if ! command -v java >/dev/null 2>&1; then
        error "Java not found"
    fi

    if ! command -v ./gradlew >/dev/null 2>&1; then
        error "Gradle wrapper not found"
    fi

    install_rust_targets
    build_rust_core
    build_deltachat

    APK_DIR="$SCRIPT_DIR/apk"
    mkdir -p "$APK_DIR"

    BUILT_APK=$(find . -name "*release*.apk" -type f | head -1)
    if [[ -n "$BUILT_APK" ]]; then
        cp "$BUILT_APK" "$APK_DIR/deltachat-android.apk"
    else
        error "No release APK found"
    fi

    APK_FILE="$APK_DIR/deltachat-android.apk"
    if [[ ! -f "$APK_FILE" ]]; then
        error "APK file not found"
    fi

    FILE_SIZE=$(stat -c%s "$APK_FILE" 2>/dev/null || stat -f%z "$APK_FILE" 2>/dev/null || echo "0")
    if [[ "$FILE_SIZE" -lt 1048576 ]]; then
        error "APK too small ($FILE_SIZE bytes)"
    fi

    if [[ -f "$SCRIPT_DIR/setup_app_apklink.sh" ]]; then
        "$SCRIPT_DIR/setup_app_apklink.sh"
    else
        warn "setup_app_apklink.sh not found"
    fi
}

main "$@"
