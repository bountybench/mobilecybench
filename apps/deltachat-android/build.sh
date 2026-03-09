#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

export LC_ALL=C
export LANG=C

# Install Rust targets (required for native build)
if ! command -v rustup >/dev/null 2>&1; then
    echo "ERROR: rustup not found. Install Rust first: https://rustup.rs"
    exit 1
fi
export PATH="$(rustup which rustc | xargs dirname):$PATH"

git submodule update --init --recursive

ACTIVE_TOOLCHAIN=$(rustup show active-toolchain | awk '{print $1}')
echo "Active Rust toolchain: $ACTIVE_TOOLCHAIN"
rustup target add x86_64-linux-android --toolchain "$ACTIVE_TOOLCHAIN"
rustup target add aarch64-linux-android --toolchain "$ACTIVE_TOOLCHAIN"
export CARGO_INCREMENTAL=1

# Setup NDK - find any available version
if [[ -z "$ANDROID_NDK_HOME" ]]; then
    ANDROID_HOME="${ANDROID_HOME:-/usr/local/lib/android/sdk}"
    if [[ -d "$ANDROID_HOME/ndk" ]]; then
        NDK_DIR=$(find "$ANDROID_HOME/ndk" -maxdepth 1 -type d -name "[0-9]*" 2>/dev/null | sort -V | tail -1)
        [[ -n "$NDK_DIR" ]] && export ANDROID_NDK_HOME="$NDK_DIR"
    fi
fi
if [[ -z "$ANDROID_NDK_HOME" ]]; then
    echo "ERROR: ANDROID_NDK_HOME not set and no NDK found in $ANDROID_HOME/ndk"
    exit 1
fi
export ANDROID_NDK_ROOT="$ANDROID_NDK_HOME"

# Build native libraries for both architectures
./scripts/ndk-make.sh x86_64
./scripts/ndk-make.sh arm64-v8a

# Write signing config (uses KEYSTORE_* env vars from build_apk.sh)
cat > gradle.properties <<EOF
DC_RELEASE_STORE_FILE=$KEYSTORE_PATH
DC_RELEASE_STORE_PASSWORD=$KEYSTORE_PASSWORD
DC_RELEASE_KEY_ALIAS=$KEYSTORE_ALIAS
DC_RELEASE_KEY_PASSWORD=$KEYSTORE_ALIAS_PASSWORD
android.defaults.buildfeatures.buildconfig=true
android.useAndroidX=true
android.nonTransitiveRClass=false
android.enableJetifier=true
org.gradle.caching=true
org.gradle.parallel=true
org.gradle.jvmargs=-Xmx4g -XX:MaxMetaspaceSize=1g -XX:+UseParallelGC
EOF

./gradlew assembleFossRelease --parallel --build-cache --no-daemon

APK=$(find . -name "*foss*release*.apk" -type f | head -1)
[[ -z "$APK" ]] && APK=$(find . -name "*release*.apk" -type f | head -1)
cp "$APK" "$SCRIPT_DIR/unsigned.apk"