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
    
    # Create local.properties for NewPipe build
    echo "sdk.dir=$ANDROID_HOME" > local.properties
    
    echo "Environment configured."
}

# Build NewPipeExtractor locally and publish to Maven local to avoid JitPack resolution issues.
build_extractor_local() {
    echo "Building NewPipeExtractor locally (v0.24.2) ..."

    # Use temp directory inside SCRIPT_DIR to avoid clutter
    EXTRACTOR_DIR="$SCRIPT_DIR/NewPipeExtractor"
    if [[ ! -d "$EXTRACTOR_DIR" ]]; then
        git clone --depth 1 --branch ../smain https://github.com/TeamNewPipe/NewPipeExtractor.git "$EXTRACTOR_DIR"
    fi

    pushd "$EXTRACTOR_DIR" >/dev/null
    # Only run clean and publish tasks, avoiding lint and tests
    ./gradlew clean publish publishToMavenLocal || {
        echo "ERROR: Failed to build NewPipeExtractor"; popd >/dev/null; exit 1;
    }
    popd >/dev/null

    echo "NewPipeExtractor has been published to Maven local repository."
}

# Make Gradle init script that adds mavenLocal() and ensures it has higher priority than remote repos. 
create_gradle_init_script() {
    INIT_SCRIPT="$SCRIPT_DIR/newpipe_local_repo.gradle"

    cat > "$INIT_SCRIPT" <<'EOF'
// Injected by setup_app.sh – adds local Maven repo for NewPipeExtractor
allprojects {
    repositories {
        mavenLocal()
    }
}
EOF

    echo "$INIT_SCRIPT"
}

# Build NewPipe APK
build_newpipe() {
    echo "Building NewPipe Android from source..."
    echo "This will take several minutes..."

    # Ensure extractor is available locally first
    build_extractor_local

    # Create init script to inject mavenLocal into all repository lists
    INIT_SCRIPT_PATH=$(create_gradle_init_script)

    ./gradlew assembleDebug --init-script "$INIT_SCRIPT_PATH" -x test -x lint
    
    echo "Build completed successfully."
}

# Install on emulator
install_newpipe() {
    echo "Installing NewPipe on Android emulator..."
    
    # Check if emulator is running
    if ! adb devices | grep -q "device\|emulator"; then
        echo "ERROR: No Android emulator found."
        echo "Please start the emulator first."
        exit 1
    fi
    
    # Attempt to locate APK dynamically (debug build)
    APK_PATH="$(find . -path "*/app/build/outputs/apk/debug/*.apk" -type f | head -n 1)"
    
    if [[ -z "$APK_PATH" ]] || [[ ! -f "$APK_PATH" ]]; then
        echo "ERROR: Could not locate debug APK to install."
        echo "Searched for */app/build/outputs/apk/debug/*.apk within $(pwd), found:"
        find . -name "*.apk" -type f 2>/dev/null | head -10
        exit 1
    fi
    
    echo "Found APK at $APK_PATH"
    adb install -r "$APK_PATH"
    echo "NewPipe installed successfully."
}

# Launch NewPipe
launch_newpipe() {
    echo "Launching NewPipe..."
    adb shell am start -n org.schabi.newpipe.debug.newplayer/org.schabi.newpipe.MainActivity
    echo "NewPipe should now be running on your emulator."
}

# Main function
main() {
    echo "NewPipe Android Setup"
    
    # Navigate to codebase directory
    if [[ ! -f "gradlew" ]]; then
        if [[ -d "codebase" ]]; then
            echo "Navigating to codebase directory..."
            cd codebase
            git checkout v0.27.7 # check out stable version
        else
            echo "ERROR: Not in NewPipe Android directory and codebase/ not found."
            echo "Please run this script from the project root or NewPipe codebase directory."
            exit 1
        fi
    fi
    
    check_prerequisites
    setup_environment
    build_newpipe
    install_newpipe
    launch_newpipe
    
    echo ""
    echo "Setup complete! NewPipe is ready for testing."
}

# Run main function
main
