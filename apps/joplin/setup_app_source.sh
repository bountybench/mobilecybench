#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
ANDROID_HOME="${HOME}/.android-sdk"
source "$ROOT_DIR/utils/android.sh"

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
    free -h
    
    #./gradlew assembleDebug
    #echo "Build completed successfully."

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

smart_cache_clear() {
    echo "Smart cache clearing - preserving working build state..."
    
    # Save current APK before any clearing
    local apk_backup=""
    if [[ -f "app/build/outputs/apk/release/app-release.apk" ]]; then
        apk_backup="/tmp/joplin-apk-backup-$(date +%s).apk"
        cp "app/build/outputs/apk/release/app-release.apk" "$apk_backup"
        echo "APK backed up to $apk_backup"
    fi
    
    # Clear only safe intermediate files
    rm -rf app/build/intermediates 2>/dev/null || true
    rm -rf app/build/tmp 2>/dev/null || true
    
    # Keep gradle wrapper and essential gradle files
    rm -rf .gradle/buildOutputCleanup/cache.properties 2>/dev/null || true
    
    # Clear Metro cache but keep React Native cache
    rm -rf node_modules/.cache 2>/dev/null || true
    
    # Only clear yarn cache, don't remove node_modules
    if command -v yarn >/dev/null 2>&1; then
        yarn cache clean || true
    fi
    
    # Restore APK if it was removed
    if [[ -n "$apk_backup" && -f "$apk_backup" && ! -f "app/build/outputs/apk/release/app-release.apk" ]]; then
        mkdir -p "app/build/outputs/apk/release/"
        cp "$apk_backup" "app/build/outputs/apk/release/app-release.apk"
        echo "APK restored from backup"
        rm "$apk_backup"
    fi
    
    echo "Smart cache clearing completed."
}

# # Saves APK
# save_apk() {
#     echo "Saving APK before cache clear..."
    
#     APK_PATH="app/build/outputs/apk/release/app-release.apk"
#     SAVE_DIR="../../../../apk_output"  
    
#     if [[ -f "$APK_PATH" ]]; then
#         mkdir -p "$SAVE_DIR"
#         cp "$APK_PATH" "$SAVE_DIR/"
#         echo "APK saved to $SAVE_DIR/app-release.apk"
#     else
#         echo "WARNING: APK not found at $APK_PATH"
#     fi
# }

# # Clear all build caches
# clear_build_cache() {
#     echo "Clearing build caches..."
    
#     # Clear Gradle cache
#     ./gradlew clean || echo "Warning: gradlew clean failed"
    
#     # Stop any running React Native processes first
#     pkill -f "react-native" 2>/dev/null || true
#     pkill -f "metro" 2>/dev/null || true
    
#     # Clear npm/yarn cache
#     yarn cache clean || echo "Warning: yarn cache clean failed"
    
#     # Clear Metro bundler cache
#     rm -rf node_modules/.cache 2>/dev/null || true
    
#     # Handle TMPDIR properly - use fallback if not set
#     local temp_dir="${TMPDIR:-/tmp}"
#     rm -rf "${temp_dir}/metro-"* 2>/dev/null || true
#     rm -rf "${temp_dir}/react-"* 2>/dev/null || true
#     rm -rf "${temp_dir}/haste-map-"* 2>/dev/null || true
    
#     # Clear Android build outputs
#     rm -rf app/build 2>/dev/null || true
#     rm -rf build 2>/dev/null || true
#     rm -rf .gradle 2>/dev/null || true
    
#     # Clear Gradle daemon and cache
#     ./gradlew --stop || echo "Warning: gradlew --stop failed"
#     rm -rf ~/.gradle/caches/ 2>/dev/null || true
#     rm -rf ~/.gradle/daemon/ 2>/dev/null || true
    
#     # Clear Watchman cache if available
#     if command -v watchman >/dev/null 2>&1; then
#         watchman watch-del-all 2>/dev/null || true
#     fi
    
#     echo "Build caches cleared."
# }

# Main function
main() {
    echo "joplin Android Setup"
    echo "==================="
    
    echo "Setting up joplin Android"
    #vm_stat       
    free -h  

    npm uninstall -g react-native-cli @react-native-community/cli
    cd codebase
    npm uninstall -g react-native-cli @react-native-community/cli
    #yarn install
    cd -

    root_dir="$(pwd)"

    if [[ -d "codebase/packages/app-mobile" ]]; then
        echo "Navigating to codebase/packages/app-mobile directory..."
        cd codebase/packages/app-mobile
    else
        echo "ERROR: Not in joplin Android directory and codebase/packages/app-mobile/ not found."
        exit 1
    fi

    yarn install
    free -h
    #npx react-native start --reset-cache > /dev/null 2>&1 &
    
    # Navigate to codebase directory
    if [[ -d "android" ]]; then
        echo "Navigating to android directory..."
        cd android
    else
        echo "ERROR: Not in joplin Android directory and codebase/packages/app-mobile/android/ not found."
        exit 1
    fi

    # Patch gradle.properties for low-RAM builds
    if [[ -f "gradle.properties" ]]; then
        echo "Patching gradle.properties for low memory usage..."
        sed -i.bak \
            -e 's/^org.gradle.jvmargs=.*/org.gradle.jvmargs=-Xmx1024m -XX:MaxMetaspaceSize=512m -XX:+UseParallelGC -Dfile.encoding=UTF-8/' \
            -e '/^org.gradle.parallel/d' \
            -e '/^android.enableR8/d' \
            gradle.properties

        # Append if missing
        grep -q '^org.gradle.parallel=false' gradle.properties || echo 'org.gradle.parallel=false' >> gradle.properties
    fi
    
    check_prerequisites
    setup_environment
    build_joplin
    #vm_stat  
    free -h  
    smart_cache_clear
    ./gradlew --stop
    #vm_stat         
    free -h  

    # save_apk
    # clear_build_cache

    #if [ -z "$CI" ]; then
    #    clear_build_cache
    #fi
    
    echo ""
    echo "Setup complete! joplin is ready for testing."
}

# Run main function
main "$@"