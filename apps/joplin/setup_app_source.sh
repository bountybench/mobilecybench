#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
ANDROID_HOME="${HOME}/.android-sdk"
source "$ROOT_DIR/utils/android.sh"

# Add alternative Maven repositories for network issues
add_maven_repos() {
    local build_gradle="app/build.gradle"
    if [[ -f "$build_gradle" ]]; then
        echo "Adding alternative Maven repositories..."
        # Add repositories before the existing repositories block
        sed -i.bak '/repositories {/a\
        maven { url "https://maven.aliyun.com/repository/google" }\
        maven { url "https://maven.aliyun.com/repository/central" }\
        maven { url "https://repo1.maven.org/maven2" }\
        maven { url "https://jcenter.bintray.com" }\
' "$build_gradle"
    fi
}

# Patch gradle.properties
patch() {
    # Patch gradle.properties for low-RAM builds
    if [[ -f "gradle.properties" ]]; then
        echo "Patching gradle.properties for low memory usage..."
        sed -i.bak \
            -e 's/^org.gradle.jvmargs=.*/org.gradle.jvmargs=-Xmx4096m -XX:MaxMetaspaceSize=1024m -XX:+UseParallelGC -Dfile.encoding=UTF-8 -Xss4m/' \
            -e '/^org.gradle.parallel/d' \
            -e '/^android.enableR8/d' \
            gradle.properties
        # Append if missing
        grep -q '^org.gradle.parallel=false' gradle.properties || echo 'org.gradle.parallel=false' >> gradle.properties
    fi
}

# Check prerequisites
check_prerequisites() {
    echo "Checking prerequisites..."
    
    # Check Java 17
    if ! command -v java >/dev/null 2>&1; then
        echo "ERROR: Java not found. Please install Java 17."
        exit 1
    fi

    if [[ ! -d "$ANDROID_HOME" && -d "/usr/local/lib/android/sdk" ]]; then
        ANDROID_HOME="/usr/local/lib/android/sdk"
    fi
    
    # Check Android SDK
    if [[ ! -d "$ANDROID_HOME" ]]; then
        echo "ERROR: Android SDK not found at $ANDROID_HOME"
        echo "Please run the Android emulator setup first."
        exit 1
    fi
    
    echo "Prerequisites verified."
}

# Setup environment
setup_environment() {
    echo "Setting up build environment..."
    
    # Set Java 17
    if [[ -d "/opt/homebrew/opt/openjdk@17" ]]; then
        export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
    elif [[ -d "/usr/lib/jvm/java-17-openjdk" ]]; then
        export JAVA_HOME=/usr/lib/jvm/java-17-openjdk
    elif command -v /usr/libexec/java_home &>/dev/null; then
        export JAVA_HOME="$(/usr/libexec/java_home -v 17)"
    else
        export JAVA_HOME=$(java -XshowSettings:properties -version 2>&1 | grep 'java.home' | awk '{print $3}')
    fi
    echo $JAVA_HOME
    export PATH="$JAVA_HOME/bin:$PATH"
    
    # Set Android SDK
    export ANDROID_HOME="$ANDROID_HOME"
    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
    
    # Create local.properties for joplin build
    echo "sdk.dir=$ANDROID_HOME" > local.properties
    
    echo "Environment configured."
}

# Build joplin APK
build_joplin() {    
    echo "Building joplin Android from source..."
    echo "This will take several minutes..."

    local temp_out=$(mktemp)
    local temp_err=$(mktemp)
    
    # Run gradle build with output suppressed
    sed -i -- 's/signingConfig signingConfigs.release/signingConfig signingConfigs.debug/' app/build.gradle
    if ./gradlew assembleRelease --no-daemon --max-workers=1 > "$temp_out" 2> "$temp_err"; then
        echo "Build completed successfully."
        # Clean up temp files on success
        rm -f "$temp_out" "$temp_err"
    else
        local exit_code=$?
        echo "ERROR: Build failed with exit code $exit_code"
        
        # Show stderr (which contains the actual error messages)
        if [[ -s "$temp_err" ]]; then
            echo "Error output:"
            cat "$temp_err"
        fi
        
        # Optionally show last part of stdout for context
        if [[ -s "$temp_out" ]]; then
            echo "Last 50 lines of build output:"
            tail -50 "$temp_out"
        fi
        
        # Clean up temp files
        rm -f "$temp_out" "$temp_err"
        exit $exit_code
    fi
}

# Copy APK to expected location for testing
copy_apk() {
    echo "Copying APK to expected location..."
    
    local apk_source="app/build/outputs/apk/release/app-release.apk"
    local apk_dest="$SCRIPT_DIR/apk"
    local apk_new_name="joplin.apk"
    
    if [[ -f "$apk_source" ]]; then
        mkdir -p "$apk_dest"
        cp "$apk_source" "$apk_dest/$apk_new_name"
        echo "APK copied to $apk_dest/$apk_new_name"
    else
        echo "WARNING: APK not found at $apk_source"
        echo "Available APKs:"
        find app/build/outputs -name "*.apk" -type f 2>/dev/null | head -5
    fi
}

clear() {
    echo "Clearing cache - preserving working build state..."
    
    rm -rf app/build/intermediates 2>/dev/null || true
    rm -rf app/build/tmp 2>/dev/null || true
    rm -rf .gradle/buildOutputCleanup/cache.properties 2>/dev/null || true
    rm -rf node_modules/.cache 2>/dev/null || true
    
    if command -v yarn >/dev/null 2>&1; then
        yarn cache clean || true
    fi
    ./gradlew --stop
    
    echo "Clearing completed."
}

sdk_patch() {
    local REL_FILE="codebase/packages/app-mobile/android/build.gradle"
    local FILE_PATH="$SCRIPT_DIR/$REL_FILE"
    local PATCH_FILE="$SCRIPT_DIR/sdk34.patch"
    if [[ ! -f "$FILE_PATH" ]]; then
        echo "SDK patch: target file missing ($FILE_PATH)" >&2; return 1
    fi
    if [[ ! -f "$PATCH_FILE" ]]; then
        echo "SDK patch: patch file not found ($PATCH_FILE)" >&2
        return 0
    fi
    cd codebase/
    git apply "$PATCH_FILE" && echo "SDK patch applied." || echo "SDK patch already applied or failed."
    cd -
}

# Main function
main() {
    echo "joplin Android Setup"
    echo "==================="
    echo "Setting up joplin Android"

    npm uninstall -g react-native-cli @react-native-community/cli
    cd codebase
    npm uninstall -g react-native-cli @react-native-community/cli
    cd -

    root_dir="$(pwd)"
    if [[ -d "codebase/packages/app-mobile" ]]; then
        sdk_patch
        echo "Navigating to codebase/packages/app-mobile directory..."
        cd codebase/packages/app-mobile
    else
        echo "ERROR: Not in joplin Android directory and codebase/packages/app-mobile/ not found."
        exit 1
    fi

    npm install -g yarn && yarn install
    
    # Navigate to codebase directory
    if [[ -d "android" ]]; then
        echo "Navigating to android directory..."
        cd android
    else
        echo "ERROR: Not in joplin Android directory and codebase/packages/app-mobile/android/ not found."
        exit 1
    fi

    patch
    add_maven_repos
    check_prerequisites
    setup_environment
    build_joplin
    copy_apk
    clear
    
    echo ""
    echo "Setup complete! joplin is ready for testing."
}

# Run main function
main "$@"