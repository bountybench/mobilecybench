#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
ANDROID_HOME="${HOME}/Android/Sdk"
source "$ROOT_DIR/utils/android.sh"

# Patch gradle.properties for low-RAM builds
patch() {
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

    # Set Java 17 or higher (Java 21 from Android Studio JBR is compatible)
    if [[ -d "$HOME/Downloads/android-studio"*"/android-studio/jbr" ]]; then
        export JAVA_HOME=$(echo $HOME/Downloads/android-studio*/android-studio/jbr | head -n1)
    elif [[ -d "/opt/homebrew/opt/openjdk@17" ]]; then
        export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
    elif [[ -d "/usr/lib/jvm/java-17-openjdk" ]]; then
        export JAVA_HOME=/usr/lib/jvm/java-17-openjdk
    elif [[ -d "/usr/lib/jvm/java-17-openjdk-amd64" ]]; then
        export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
    elif command -v /usr/libexec/java_home &>/dev/null; then
        export JAVA_HOME="$(/usr/libexec/java_home -v 17)"
    else
        export JAVA_HOME=$(java -XshowSettings:properties -version 2>&1 | grep 'java.home' | awk '{print $3}')
    fi
    echo "JAVA_HOME=$JAVA_HOME"
    export PATH="$JAVA_HOME/bin:$PATH"

    # Verify Java is now accessible
    if ! command -v java >/dev/null 2>&1; then
        echo "ERROR: Java not found after environment setup."
        exit 1
    fi
    echo "Java version: $(java -version 2>&1 | head -n 1)"

    # Set Android SDK
    export ANDROID_HOME="$ANDROID_HOME"
    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"

    # Create local.properties
    echo "sdk.dir=$ANDROID_HOME" > local.properties

    echo "Environment configured."
}

# Build Grocy APK
build_grocy() {
    echo "Building Grocy Android from source..."
    echo "This will take several minutes..."

    local temp_out=$(mktemp)
    local temp_err=$(mktemp)

    # Pre-download Gradle wrapper to avoid timeout issues
    echo "Pre-downloading Gradle wrapper..."
    ./gradlew --version > /dev/null 2>&1 || {
        echo "Gradle wrapper download failed, trying with increased timeout..."
        export GRADLE_OPTS="-Dorg.gradle.internal.http.connectionTimeout=300000 -Dorg.gradle.internal.http.socketTimeout=300000"
        ./gradlew --version > /dev/null 2>&1
    }

    # Build release variant (uses debug signing automatically, no .debug suffix)
    echo "Building release APK..."
    if ./gradlew assembleRelease --no-daemon --max-workers=2 > "$temp_out" 2> "$temp_err"; then
        echo "Build completed successfully."
        rm -f "$temp_out" "$temp_err"
    else
        local exit_code=$?
        echo "ERROR: Build failed with exit code $exit_code"

        if [[ -s "$temp_err" ]]; then
            echo "Error output:"
            cat "$temp_err"
        fi

        if [[ -s "$temp_out" ]]; then
            echo "Last 50 lines of build output:"
            tail -50 "$temp_out"
        fi

        rm -f "$temp_out" "$temp_err"
        exit $exit_code
    fi
}

# Sign and copy APK to expected location
copy_apk() {
    echo "Signing and copying APK to expected location..."

    local apk_unsigned="app/build/outputs/apk/release/app-release-unsigned.apk"
    local apk_dest="$SCRIPT_DIR/apk"
    local apk_new_name="grocy.apk"

    if [[ -f "$apk_unsigned" ]]; then
        mkdir -p "$apk_dest"

        # Keystore configuration (shared across apps in utils/)
        local keystore_dir="$ROOT_DIR/utils"
        local keystore_name="$keystore_dir/benchmark.keystore"
        local keystore_pass="password"
        local key_alias="benchmark-key"

        # Create keystore if it doesn't exist
        if [ ! -f "$keystore_name" ]; then
            echo "Creating signing keystore..."
            keytool -genkey -v -keystore "$keystore_name" \
                    -alias "$key_alias" -keyalg RSA -keysize 2048 \
                    -validity 10000 -storepass "$keystore_pass" -keypass "$keystore_pass" \
                    -dname "CN=Benchmark, OU=Test, O=Test, L=Test, S=Test, C=US"
        fi

        # Sign the APK
        echo "Signing APK..."
        local apksigner="$ANDROID_HOME/build-tools/*/apksigner"
        apksigner=$(ls $apksigner 2>/dev/null | head -1)

        if [ -z "$apksigner" ]; then
            echo "ERROR: apksigner not found in ANDROID_HOME/build-tools"
            exit 1
        fi

        $apksigner sign --ks "$keystore_name" --ks-pass "pass:$keystore_pass" \
                  --out "$apk_dest/$apk_new_name" "$apk_unsigned"

        echo "APK signed and copied to $apk_dest/$apk_new_name"
        ls -lh "$apk_dest/$apk_new_name"
    else
        echo "ERROR: Unsigned APK not found at $apk_unsigned"
        echo "Available APKs:"
        find app/build/outputs -name "*.apk" -type f 2>/dev/null | head -5
        exit 1
    fi
}

# Clear build cache
clear_cache() {
    echo "Clearing build cache..."

    rm -rf app/build/intermediates 2>/dev/null || true
    rm -rf app/build/tmp 2>/dev/null || true
    rm -rf .gradle/buildOutputCleanup/cache.properties 2>/dev/null || true

    ./gradlew --stop 2>/dev/null || true

    echo "Cache cleared."
}

# Main function
main() {
    echo "Grocy Android Setup"
    echo "==================="

    # Navigate to codebase directory
    if [[ -d "codebase" ]]; then
        echo "Navigating to codebase directory..."
        cd codebase
    else
        echo "ERROR: codebase directory not found."
        exit 1
    fi

    patch
    check_prerequisites
    setup_environment
    build_grocy
    copy_apk
    clear_cache

    echo ""
    echo "Setup complete! Grocy Android is ready for testing."
    echo "APK location: apk/grocy.apk"
}

# Run main function
main "$@"
