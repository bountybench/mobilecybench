
#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANDROID_HOME="${HOME}/.android-sdk"

# Check prerequisites
check_prerequisites() {
    echo "Checking prerequisites..."
    
    # Check Java 17
    if ! command -v java >/dev/null 2>&1; then
        echo "ERROR: Java not found. Please install Java 17."
        exit 1
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
    export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
    export PATH="$JAVA_HOME/bin:$PATH"
    
    # Set Android SDK
    export ANDROID_HOME="$ANDROID_HOME"
    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
    
    # Create local.properties for Tindroid build
    echo "sdk.dir=$ANDROID_HOME" > local.properties

    # Create keystore.properties for Tindroid build
    if [ ! -f keystore.properties ]; then
        echo "storeFile=debug.keystore
storePassword=android
keyAlias=androiddebugkey
keyPassword=android" >> keystore.properties
    else
    echo "storeFile=debug.keystore
storePassword=android
keyAlias=androiddebugkey
keyPassword=android" > keystore.properties
    fi

    # There should be a dummy google-services.json file in the Tindroid root directory.
    # The Tindroid app requires Firebase services for all build variants.
    # Copy google-services.json from the Tindroid root directory to app/google-services.json inside the codebase directory.
    if [ ! -f ../google-services.json ]; then
        echo "ERROR: google-services.json not found in the Tindroid root directory."
        echo "Please copy a valid google-services.json file to the Tindroid root directory."
        exit 1
    else
        cp "../google-services.json" "app/google-services.json"
    fi
    
    echo "Environment configured."
}

# Build Tindroid APK
build_tindroid() {
    echo "Building Tindroid Android from source..."
    echo "This will take several minutes..."
    
    # Build with Gradle and override JVM args to fix Java 8+ compatibility
    ./gradlew assembleDebug -Dorg.gradle.jvmargs="-Xmx4096m -XX:+HeapDumpOnOutOfMemoryError -Dfile.encoding=UTF-8"
    
    echo "Build completed successfully."
}

# Install on emulator
install_tindroid() {
    echo "Installing Tindroid on Android emulator..."
    
    # Check if emulator is running
    if ! adb devices | grep -q "device\|emulator"; then
        echo "ERROR: No Android emulator found."
        echo "Please start the emulator first."
        exit 1
    fi
    
    # Install universal APK with correct path
    APK_PATH="app/build/outputs/apk/debug/app-debug.apk"
    
    if [[ ! -f $APK_PATH ]]; then
        echo "ERROR: APK not found at $APK_PATH"
        echo "Available APKs:"
        find app/build/outputs -name "*.apk" -type f 2>/dev/null | head -10
        exit 1
    fi
    
    adb install "$APK_PATH"
    echo "Tindroid installed successfully."
}

# Setup connection to local Tinode server
setup_local_server_connection() {
    echo "Configuring connection to local Tinode server..."
    
    # Verify local Tinode server is accessible
    # By default, Tindroid debug build will connect to Tinode server at 10.0.2.2:6060 (emulator)
    echo "Checking local Tinode server accessibility..."
    if curl -s http://localhost:6060 >/dev/null 2>&1; then
        echo "✅ Local Tinode server is running and accessible"
    else
        echo "⚠️  Warning: Local Tinode server may not be accessible at localhost:6060"
        echo "   Make sure your Tinode server is running: docker ps"
    fi
}

# Launch Tindroid
launch_tindroid() {
    echo "Launching Tindroid..."
    adb shell am start -n co.tinode.tindroidx/co.tinode.tindroid.InitRouterActivity
    echo "Tindroid should now be running on your emulator."
    echo ""
    echo "If connecting to local server, use: 10.0.2.2:6060 (emulator) or 192.168.4.41:6060 (device)"
}

# Main function
main() {
    echo "Tindroid Android Setup"
    echo "==================="
    
    # Navigate to codebase directory
    if [[ ! -f "gradlew" ]]; then
        if [[ -d "codebase" ]]; then
            echo "Navigating to codebase directory..."
            cd codebase
        else
                    echo "ERROR: Not in Tindroid Android directory and codebase/ not found."
        echo "Please run this script from the project root or Tindroid codebase directory."
            exit 1
        fi
    fi
    
    check_prerequisites
    setup_environment
    build_tindroid
    install_tindroid
    setup_local_server_connection
    launch_tindroid
    
    echo ""
    echo "Setup complete! Tindroid is ready for testing."
}

# Run main function
main "$@"
