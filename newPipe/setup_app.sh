#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANDROID_HOME="${HOME}/.android-sdk"

# check prerequisites
check_prerequisites() {
    echo "Checking prerequisites..."
    
    # check Java 17
    if ! command -v java >/dev/null 2>&1; then
        echo "ERROR: Java not found. Please install Java 17."
        exit 1
    fi
    
    # check Android SDK
    if [[ ! -d "$ANDROID_HOME" ]]; then
        echo "ERROR: Android SDK not found at $ANDROID_HOME"
        exit 1
    fi
    
    echo "Prerequisites verified."
}

# setup environment
setup_environment() {
    echo "Setting up build environment..."
    
    # set Java 17
    export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
    export PATH="$JAVA_HOME/bin:$PATH"
    
    # set Android SDK
    export ANDROID_HOME="$ANDROID_HOME"
    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
    
    # create local.properties for NewPipe build
    echo "sdk.dir=$ANDROID_HOME" > local.properties
    echo "Environment configured."
}

# build NewPipeExtractor locally and publish to Maven local to avoid JitPack resolution issues; necessary for NewPipe build
build_extractor_local() {
    echo "Building NewPipeExtractor locally..."

    # set temp directory inside SCRIPT_DIR to avoid clutter
    EXTRACTOR_DIR="$SCRIPT_DIR/NewPipeExtractor"
    if [[ ! -d "$EXTRACTOR_DIR" ]]; then
        git clone --depth 1 --branch master https://github.com/TeamNewPipe/NewPipeExtractor.git "$EXTRACTOR_DIR"
    fi

    pushd "$EXTRACTOR_DIR" >/dev/null
    # only run clean and publish tasks, avoiding lint and tests
    ./gradlew clean publish publishToMavenLocal || { echo "ERROR: Failed to build NewPipeExtractor"; popd >/dev/null; exit 1; }
    popd >/dev/null

    echo "NewPipeExtractor published to Maven local repository."
}

# make Gradle init script that adds mavenLocal() and ensures it has higher priority than remote repos
create_gradle_init_script() {
    INIT_SCRIPT="$SCRIPT_DIR/newpipe_local_repo.gradle"

    cat > "$INIT_SCRIPT" <<'EOF'
// add local Maven repo for NewPipeExtractor
allprojects {
    repositories {
        mavenLocal()
    }
}
EOF

    echo "$INIT_SCRIPT"
}

# build NewPipe APK
build_newpipe() {
    echo "Building NewPipe Android from source..."

    build_extractor_local # ensure extractor is available locally first
    INIT_SCRIPT_PATH=$(create_gradle_init_script) # create init script to inject mavenLocal into all repo lists
    ./gradlew assembleDebug --init-script "$INIT_SCRIPT_PATH" -x test -x lint

    echo "Build completed successfully."
}

# install on emulator
install_newpipe() {
    echo "Installing NewPipe on Android emulator..."
    
    # check if emulator is running
    if ! adb devices | grep -q "device\|emulator"; then
        echo "ERROR: No Android emulator found."
        exit 1
    fi
    
    # locate APK dynamically (debug build)
    APK_PATH="$(find . -path "*/app/build/outputs/apk/debug/*.apk" -type f | head -n 1)"
    
    if [[ -z "$APK_PATH" ]] || [[ ! -f "$APK_PATH" ]]; then
        echo "ERROR: Could not locate debug APK to install. Available APKs:"
        find . -name "*.apk" -type f 2>/dev/null | head -10
        exit 1
    fi
    
    echo "Found APK at $APK_PATH"
    adb install -r "$APK_PATH"
    echo "NewPipe installed successfully."
}

# launch NewPipe
launch_newpipe() {
    echo "Launching NewPipe..."
    adb shell am start -n org.schabi.newpipe.debug.HEAD/org.schabi.newpipe.MainActivity
    echo "NewPipe now be running on your emulator."
}

main() {
    echo "NewPipe Android Setup"
    
    # navigate to codebase directory
    if [[ ! -f "gradlew" ]]; then
        if [[ -d "codebase" ]]; then
            echo "Navigating to codebase directory..."
            cd codebase && git checkout v0.27.7 # check out stable version
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
    
    echo "Setup complete! NewPipe is ready for testing."
}

main
