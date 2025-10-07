#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Respect an existing ANDROID_HOME/ANDROID_SDK_ROOT if already provided by CI, otherwise discover.
if [ -z "${ANDROID_HOME}" ]; then
    if [ -n "${ANDROID_SDK_ROOT}" ]; then
        ANDROID_HOME="${ANDROID_SDK_ROOT}"
    else
        # Common fallback locations (GitHub Actions, local installs, custom installs)
        for cand in "/usr/local/lib/android/sdk" "$HOME/Android/Sdk" "$HOME/.android-sdk" "/opt/android-sdk"; do
            if [ -d "$cand" ]; then
                ANDROID_HOME="$cand"
                break
            fi
        done
    fi
fi

# Final fallback (will likely not exist yet; prerequisite check will handle)
: "${ANDROID_HOME:=$HOME/.android-sdk}"


# Check prerequisites
check_prerequisites() {
    echo "[home-assistant-android][prereq] Checking prerequisites..."

    if ! command -v java >/dev/null 2>&1; then
        echo "Java not found. Please install Java 17 (actions/setup-java in CI)."
        exit 1
    fi

    if [ ! -d "$ANDROID_HOME" ]; then
        echo "Android SDK not found. Searched path: $ANDROID_HOME"
        echo "Set ANDROID_HOME or ANDROID_SDK_ROOT before invoking this script (CI step to install SDK)."
        exit 1
    fi

    echo "Using ANDROID_HOME=$ANDROID_HOME"
    echo "Prerequisites verified."
}

# Setup environment
setup_environment() {
    echo "Setting up build environment..."

    # Set Java 17 - use existing JAVA_HOME if available, otherwise fallback to macOS path
    if [[ -n "$JAVA_HOME" && -d "$JAVA_HOME" ]]; then
        echo "Using existing JAVA_HOME: $JAVA_HOME"
    elif [[ -d "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home" ]]; then
        export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
        echo "Using macOS Homebrew JAVA_HOME: $JAVA_HOME"
    elif [[ -d "/usr/lib/jvm/java-17-openjdk" ]]; then
        export JAVA_HOME=/usr/lib/jvm/java-17-openjdk
        echo "Using Linux JAVA_HOME: $JAVA_HOME"
    else
        echo "Could not find Java 17 via known paths. Using system default."
        export JAVA_HOME=$(java -XshowSettings:properties -version 2>&1 | grep 'java.home' | awk '{print $3}')
    fi
    
    # Create local.properties for Home Assistant build
    echo "sdk.dir=$ANDROID_HOME" > local.properties

    # Generate mock keystore for app/ if it doesn't exist
    if [ ! -f app/release_keystore.keystore ]; then
        keytool -genkeypair -v -keystore app/release_keystore.keystore -alias release -keyalg RSA -keysize 2048 -validity 10000 -storepass android -keypass android -dname "CN=Android Debug,O=Home Assistant,C=US"
    fi
    # Generate mock keystore for wear/ if it doesn't exist
    if [ ! -f wear/release_keystore.keystore ]; then
        keytool -genkeypair -v -keystore wear/release_keystore.keystore -alias release -keyalg RSA -keysize 2048 -validity 10000 -storepass android -keypass android -dname "CN=Android Debug,O=Home Assistant,C=US"
    fi
    # Generate mock keystore for automotive/ if it doesn't exist
    if [ ! -f automotive/release_keystore.keystore ]; then
        keytool -genkeypair -v -keystore automotive/release_keystore.keystore -alias release -keyalg RSA -keysize 2048 -validity 10000 -storepass android -keypass android -dname "CN=Android Debug,O=Home Assistant,C=US"
    fi
    
    # Set environment variables to match the keystore passwords we created
    # This ensures the build system uses the correct passwords
    export KEYSTORE_PASSWORD="android"
    export KEYSTORE_ALIAS="release"  
    export KEYSTORE_ALIAS_PASSWORD="android"
    
    # There should be a dummy google-services.json file in the Home Assistant root directory.
    # The Home Assistant app requires Firebase services for all build variants.
    # Copy google-services.json from the Home Assistant root directory to app/google-services.json inside the codebase directory.
    if [ ! -f ../google-services.json ]; then
        echo "ERROR: google-services.json not found in the Home Assistant root directory."
        echo "Please copy a valid google-services.json file to the Home Assistant root directory."
        exit 1
    else
        cp "../google-services.json" "app/google-services.json"
        cp "../google-services.json" "automotive/google-services.json"
        cp "../google-services.json" "wear/google-services.json"

    fi
    
    echo "Environment configured."
}

# Build Home Assistant APK
build_home_assistant() {
    echo "Building Home Assistant..."
    echo "This may take several minutes..."
    git submodule update --init --recursive
    ./gradlew --no-daemon clean
    ./gradlew --no-daemon --max-workers=1 \
    app:assembleMinimalRelease \
    -Dorg.gradle.jvmargs="-Xmx2048m" \
    -Dorg.gradle.parallel=false \
    -PnoLeakCanary \
    --write-locks
    echo "Build completed successfully."
}

# Export built APK to apk directory
export_apk() {
    echo "Exporting APK to apk directory..."
    
    apk="app/build/outputs/apk/minimal/release/app-minimal-release.apk"
    
    if [ ! -f "$apk" ]; then
        echo "ERROR: APK not found at $apk"
        echo "Available APKs:"
        find app/build/outputs -name "*.apk" -type f 2>/dev/null | head -10
        exit 1
    fi
    
    APK_DIR="../apk"
    mkdir -p "$APK_DIR"
    
    out="$APK_DIR/home-assistant-minimal-release.apk"
    cp -f "$apk" "$out"
    
    echo "APK exported to: $out"
}

perform_cleanup() {
    echo "Clearing cache..."
    
    rm -rf app/build/intermediates 2>/dev/null || true
    rm -rf app/build/tmp 2>/dev/null || true
    rm -rf .gradle/buildOutputCleanup/cache.properties 2>/dev/null || true
}

# Main function
main() {
    echo "Home Assistant Setup"
    echo "==================="
    
    # Navigate to codebase directory
    if [[ ! -f "gradlew" ]]; then
        if [[ -d "codebase" ]]; then
            echo "Navigating to codebase directory..."
            cd codebase
        else
            echo "ERROR: Not in Home Assistant directory and codebase/ not found."
        echo "Please run this script from the project root or Home Assistant codebase directory."
            exit 1
        fi
    fi
    
    check_prerequisites
    setup_environment
    build_home_assistant
    export_apk
    perform_cleanup

    echo "Setup complete! Home Assistant APK is ready at ../apk/app-minimal-release.apk"
}

# Run main
main "$@"