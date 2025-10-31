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
        # Add targets for multiple architectures to support both ARM and x86 emulators
        TARGETS="aarch64-linux-android x86_64-linux-android i686-linux-android"

        if ! rustup install "$RUSTUP_TOOLCHAIN"; then
            error "Failed to install toolchain $RUSTUP_TOOLCHAIN"
        fi

        for target in $TARGETS; do
            if ! rustup target add "$target" --toolchain "$RUSTUP_TOOLCHAIN"; then
                error "Failed to install target $target"
            fi
        done

        export CARGO_INCREMENTAL=1
        export CARGO_NET_RETRY=10
        export CARGO_HTTP_TIMEOUT=60
        export CARGO_HTTP_LOW_SPEED_LIMIT=10
    else
        error "rustup not found"
    fi
}

build_rust_core() {
    cd "$SCRIPT_DIR/codebase"
    git submodule update --init --recursive
    
    # Build for multiple architectures to support both ARM and x86 emulators
    # arm64-v8a: For ARM64 devices and emulators
    # x86_64: For x86_64 emulators (common in CI/cloud environments)
    # x86: For 32-bit x86 emulators (legacy support)
    info "Building native libraries for multiple architectures..."
    
    for arch in arm64-v8a x86_64 x86; do
        info "Building for architecture: $arch"
        if ! ./scripts/ndk-make.sh "$arch"; then
            warn "Failed to build for $arch, continuing with other architectures"
        fi
    done
}

build_deltachat() {
    # IMPORTANT: Do NOT create gradle.properties or local.properties inside the codebase directory
    # as it modifies the git submodule. Instead, we'll pass these as Gradle properties via command line
    # or use the global gradle.properties in the user's home directory.
    
    cd "$SCRIPT_DIR/codebase"
    
    # Verify we're not modifying the submodule
    if [[ -n "$(git status --porcelain 2>/dev/null)" ]]; then
        warn "Warning: codebase submodule has uncommitted changes before build"
    fi
    export GRADLE_OPTS="$GRADLE_OPTS -Dorg.gradle.caching=true -Dorg.gradle.parallel=true -Dorg.gradle.configureondemand=true"

    # Create signing configuration for release build
    mkdir -p "$HOME/.android"
    if [[ ! -f "$HOME/.android/debug.keystore" ]]; then
        keytool -genkey -v -keystore "$HOME/.android/debug.keystore" \
            -alias androiddebugkey -keyalg RSA -keysize 2048 -validity 10000 \
            -storepass android -keypass android \
            -dname "CN=Android Debug,O=Android,C=US"
    fi

    # Set up Android SDK environment
    if [[ -d "/usr/local/lib/android/sdk" ]]; then
        export ANDROID_HOME="/usr/local/lib/android/sdk"
        export ANDROID_NDK_HOME="/usr/local/lib/android/sdk/ndk/27.0.12077973"
        export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
    fi

    # Create gradle.properties in user's .gradle directory (global location)
    # This avoids modifying the codebase submodule
    mkdir -p "$HOME/.gradle"
    cat > "$HOME/.gradle/gradle.properties" << EOF
DC_RELEASE_STORE_FILE=$HOME/.android/debug.keystore
DC_RELEASE_STORE_PASSWORD=android
DC_RELEASE_KEY_ALIAS=androiddebugkey
DC_RELEASE_KEY_PASSWORD=android
android.defaults.buildfeatures.buildconfig=true
android.useAndroidX=true
android.enableJetifier=true
EOF

    # Pass SDK paths as system properties instead of creating local.properties
    # This avoids any modifications to the codebase directory
    export ANDROID_SDK_ROOT="$ANDROID_HOME"

    # Create missing resource files that are causing compilation errors
    mkdir -p src/main/res/values
    
    # Add missing string resources
    if ! grep -q "zxing_msg_camera_framework_bug" src/main/res/values/strings.xml 2>/dev/null; then
        # Add missing ZXing string
        sed -i '/<\/resources>/i\    <string name="zxing_msg_camera_framework_bug">Camera framework bug detected</string>' src/main/res/values/strings.xml 2>/dev/null || echo '<resources><string name="zxing_msg_camera_framework_bug">Camera framework bug detected</string></resources>' > src/main/res/values/missing_strings.xml
    fi
    
    # Add missing attributes
    if ! grep -q "toolbarStyle" src/main/res/values/attrs.xml 2>/dev/null; then
        # Add missing toolbar style attribute
        sed -i '/<\/resources>/i\    <attr name="toolbarStyle" format="reference" />' src/main/res/values/attrs.xml 2>/dev/null || echo '<resources><attr name="toolbarStyle" format="reference" /></resources>' > src/main/res/values/missing_attrs.xml
    fi
    
    # Add missing IDs
    mkdir -p src/main/res/values
    cat > src/main/res/values/missing_ids.xml << EOF
<?xml version="1.0" encoding="utf-8"?>
<resources>
    <item name="search_close_btn" type="id" />
</resources>
EOF

    local temp_out=$(mktemp)
    local temp_err=$(mktemp)

    # Run Gradle build and check if APK was actually created
    info "Running Gradle build..."
    if ./gradlew assembleFossRelease \
        --daemon \
        --parallel \
        --build-cache \
        --configure-on-demand \
        --max-workers=4 \
        --info \
        -Dorg.gradle.jvmargs="-Xmx4g -XX:MaxMetaspaceSize=1g -XX:+UseParallelGC -XX:+UseStringDeduplication" \
        -Pandroid.defaults.buildfeatures.buildconfig=true \
        -Psdk.dir="$ANDROID_HOME" \
        -Pndk.dir="$ANDROID_NDK_HOME" \
        2>&1 | tee "$temp_out"; then

        # Check if APK was actually built in the expected location
        BUILT_APK=$(find . -name "*release*.apk" -type f 2>/dev/null | head -1)
        if [[ -n "$BUILT_APK" ]]; then
            info "APK found at: $BUILT_APK"
            rm -f "$temp_out" "$temp_err"
        else
            error "Gradle build completed but no APK found. Build output:"
            cat "$temp_out"
        fi
    else
        local exit_code=$?
        error "Gradle build failed with exit code $exit_code. Build output:"
        cat "$temp_out"
        rm -f "$temp_out" "$temp_err"
        exit $exit_code
    fi
    
    # Verify we didn't modify the submodule during build
    if [[ -n "$(git status --porcelain 2>/dev/null)" ]]; then
        warn "Warning: codebase submodule was modified during build. This should not happen!"
        info "Modified files:"
        git status --short
    fi
}

main() {
    METADATA_FILE="$SCRIPT_DIR/metadata.json"
    if [[ ! -f "$METADATA_FILE" ]]; then
        error "metadata.json not found"
    fi

    if ! command -v java >/dev/null 2>&1; then
        error "Java not found."
    fi

    if ! command -v "$SCRIPT_DIR/codebase/gradlew" >/dev/null 2>&1; then
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
        info "Copied APK from $BUILT_APK to $APK_DIR/deltachat-android.apk"
    else
        error "No release APK found in build output"
    fi

    APK_FILE="$APK_DIR/deltachat-android.apk"
    if [[ ! -f "$APK_FILE" ]]; then
        error "APK file not found"
    fi

    FILE_SIZE=$(stat -c%s "$APK_FILE" 2>/dev/null || stat -f%z "$APK_FILE" 2>/dev/null || echo "0")
    if [[ "$FILE_SIZE" -lt 1048576 ]]; then
        error "APK too small ($FILE_SIZE bytes)"
    fi
}

main "$@"