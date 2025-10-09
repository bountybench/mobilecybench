#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
ANDROID_HOME="${HOME}/.android-sdk"
source "$ROOT_DIR/utils/android.sh"

# Patch gradle.properties
patch() {
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
}

# Check prerequisites
check_prerequisites() {
    echo "Checking prerequisites..."
    
    # Check Java 21
    if ! command -v java >/dev/null 2>&1; then
        echo "ERROR: Java not found. Please install Java 21."
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
    
    # Set Java 21
    if [[ -d "/opt/homebrew/opt/openjdk@21" ]]; then
        export JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home
    elif [[ -d "/usr/lib/jvm/java-21-openjdk" ]]; then
        export JAVA_HOME=/usr/lib/jvm/java-21-openjdk
    elif command -v /usr/libexec/java_home &>/dev/null; then
        export JAVA_HOME="$(/usr/libexec/java_home -v 21)"
    elif [[ -d "/c/Program Files/Java/jdk-21" ]]; then
        export JAVA_HOME="/c/Program Files/Java/jdk-21"
    else
        export JAVA_HOME=$(java -XshowSettings:properties -version 2>&1 | grep 'java.home' | awk '{print $3}')
    fi
    echo $JAVA_HOME
    export PATH="$JAVA_HOME/bin:$PATH"
    
    # Set Android SDK
    export ANDROID_HOME="$ANDROID_HOME"
    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
    
    # Create local.properties for audiobookshelf build
    echo "sdk.dir=$ANDROID_HOME" > local.properties
    
    echo "Environment configured."
}

# Build audiobookshelf APK
build_audiobookshelf() {    
    echo "Building audiobookshelf Android from source..."
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

    sign_apk
}

# Sign the release APK with debug keystore
sign_apk() {
    echo "Signing release APK..."

    KEYSTORE_FILE="$HOME/.android/debug.keystore"
    
    # Check if the debug keystore exists, and create it if it doesn't.
    if [ ! -f "$KEYSTORE_FILE" ]; then
        echo "Debug keystore not found. Generating a new one..."
        mkdir -p "$HOME/.android/"
        keytool -genkey -v -keystore "$KEYSTORE_FILE" \
                -alias androiddebugkey -keyalg RSA -keysize 2048 \
                -validity 10000 -storepass android -keypass android \
                -dname "CN=Android Debug, O=Android, C=US"
        echo "Debug keystore generated at $KEYSTORE_FILE"
    fi
    
    APK_UNSIGNED=$(find app/build/outputs/apk/release/ -name "*-release-unsigned.apk" -type f 2>/dev/null | head -1)
    
    if [[ -z "$APK_UNSIGNED" ]]; then
        echo "No unsigned APK found to sign"
    fi
    
    echo "Signing APK: $APK_UNSIGNED"
    
    # Use apksigner instead of deprecated jarsigner
    if [[ -z "$ANDROID_HOME" ]]; then
        fail "ANDROID_HOME not set, cannot find apksigner"
    fi
    
    APKSIGNER="$ANDROID_HOME/build-tools/*/apksigner"
    # Fix path for Windows MinGW users
    if [[ "$OSTYPE" == "msys" ]]; then
        {
            APKSIGNER="$ANDROID_HOME/build-tools/*/apksigner.bat"
        }
    fi
    APKSIGNER=$(ls $APKSIGNER 2>/dev/null | head -1)
    
    if [[ ! -f "$APKSIGNER" ]]; then
        echo "apksigner not found, falling back to jarsigner"
        jarsigner -verbose -sigalg SHA256withRSA -digestalg SHA256 -keystore "$HOME/.android/debug.keystore" -storepass android -keypass android "$APK_UNSIGNED" androiddebugkey
    else
        echo "Using apksigner: $APKSIGNER"
        "$APKSIGNER" sign --ks "$HOME/.android/debug.keystore" --ks-key-alias androiddebugkey --ks-pass pass:android --key-pass pass:android --v2-signing-enabled true "$APK_UNSIGNED"
    fi
    
    APK_SIGNED="${APK_UNSIGNED/-unsigned.apk/.apk}"
    echo $APK_SIGNED
    mv "$APK_UNSIGNED" "$APK_SIGNED"
    
    echo "Signed APK: $APK_SIGNED"
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

# Main function
main() {
    echo "audiobookshelf Android Setup"
    echo "==================="
    
    echo "Setting up audiobookshelf Android"

    # npm uninstall -g react-native-cli @react-native-community/cli
    cd codebase
    # npm uninstall -g react-native-cli @react-native-community/cli
    cd -

    root_dir="$(pwd)"

    if [[ -d "codebase/" ]]; then
        echo "Navigating to codebase/ directory..."
        cd codebase/
    else
        echo "ERROR: Not in audiobookshelf Android directory and codebase/ not found."
        exit 1
    fi

    npm install
    npm run generate
    npx cap sync
    
    # Navigate to codebase directory
    if [[ -d "android" ]]; then
        echo "Navigating to android directory..."
        cd android
    else
        echo "ERROR: Not in audiobookshelf Android directory and codebase/android/ not found."
        exit 1
    fi

    patch
    check_prerequisites
    setup_environment
    build_audiobookshelf
    clear

    echo "Moving audiobookshelf APK to apk/audiobookshelf.apk"
    mkdir -p ../../apk
    mv app/build/outputs/apk/release/app-release.apk ../../apk/audiobookshelf.apk
    
    echo ""
    echo "Setup complete! audiobookshelf is ready for testing."
}

# Run main function
main "$@"