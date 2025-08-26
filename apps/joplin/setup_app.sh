#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
ANDROID_HOME="${HOME}/.android-sdk"
source "$ROOT_DIR/utils/android.sh"

# Install on emulator
install_joplin() {
    echo "Installing joplin on Android emulator..."
    
    # Check if emulator is running
    if ! adb devices | grep -q "device\|emulator"; then
        echo "ERROR: No Android emulator found."
        echo "Please start the emulator first."
        exit 1
    fi
    
    # Install universal APK with correct path
    APK_PATH="app/build/outputs/apk/release/app-release.apk"
    
    if [[ ! -f $APK_PATH ]]; then
        echo "ERROR: APK not found at $APK_PATH"
        echo "Available APKs:"
        find app/build/outputs -name "*.apk" -type f 2>/dev/null | head -10
        exit 1
    fi
    
    adb install "$APK_PATH"
    echo "joplin installed successfully."
}

# Clear ALL build caches - run after app installation
clear_all_build_cache() {
    echo "Clearing ALL build caches and temporary files..."
    
    # Stop any running processes first
    echo "Stopping running processes..."
    pkill -f "react-native" 2>/dev/null || true
    pkill -f "metro" 2>/dev/null || true
    pkill -f "node" 2>/dev/null || true
    pkill -f "gradle" 2>/dev/null || true
    
    # Stop Gradle daemon
    ./gradlew --stop 2>/dev/null || true
    
    # Clear Gradle build outputs and cache
    echo "Clearing Gradle caches..."
    ./gradlew clean || echo "Warning: gradlew clean failed"
    rm -rf app/build 2>/dev/null || true
    rm -rf build 2>/dev/null || true
    rm -rf .gradle 2>/dev/null || true
    rm -rf ~/.gradle/caches/ 2>/dev/null || true
    rm -rf ~/.gradle/daemon/ 2>/dev/null || true
    rm -rf ~/.gradle/wrapper/dists/ 2>/dev/null || true
    
    # Clear Node.js/NPM/Yarn caches
    echo "Clearing Node.js and package manager caches..."
    yarn cache clean 2>/dev/null || true
    npm cache clean --force 2>/dev/null || true
    rm -rf node_modules/.cache 2>/dev/null || true
    rm -rf ~/.npm/_cacache 2>/dev/null || true
    rm -rf ~/.yarn/cache 2>/dev/null || true
    
    # Clear React Native and Metro caches
    echo "Clearing React Native and Metro caches..."
    rm -rf node_modules/.cache 2>/dev/null || true
    
    # Clear Watchman cache if available
    if command -v watchman >/dev/null 2>&1; then
        echo "Clearing Watchman cache..."
        watchman watch-del-all 2>/dev/null || true
    fi
    
    # Clear Android build caches
    echo "Clearing Android build caches..."
    rm -rf app/build/intermediates 2>/dev/null || true
    rm -rf app/build/generated 2>/dev/null || true
    rm -rf app/build/tmp 2>/dev/null || true
    rm -rf app/.cxx 2>/dev/null || true
    
    echo "All build caches and temporary files cleared successfully."
}

# Launch joplin
launch_joplin() {
    echo "Launching joplin..."
    adb_launch_activity "net.cozic.joplin/.MainActivity"
    echo "joplin should now be running on your emulator."
}

# Synching with server
synch_with_server() {
    echo "Synching app with server..."
    pip install uiautomator2
    python synch_app.py --username usera@localhost --password userAPW123
    echo "Should now be synched with server."
}

# Main function
main() {
    echo "joplin Android Setup"
    echo "==================="
    
    echo "Setting up joplin Android"

    root_dir="$(pwd)"
    cd codebase/packages/app-mobile/android
    install_joplin
    #clear_all_build_cache
    launch_joplin
    cd "$root_dir"
    synch_with_server

    adb root

    local immutable_dirs=(/system /vendor /product /odm)
    adb_hash_dirs "${immutable_dirs[@]}" > baseline.json

    local secret_dirs=(/data/cache /data/misc)
    adb_hide_secret_files "secrets.json" "${secret_dirs[@]}"

    adb unroot
    
    echo ""
    echo "Setup complete! joplin is ready for testing."
}

# Run main function
main "$@"