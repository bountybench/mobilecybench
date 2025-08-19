#!/bin/bash
set -e

# Resolve stable paths no matter where this script is invoked from
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# The Bitwarden app directory (this script's directory)
PROJECT_ROOT="$SCRIPT_DIR"

# Resolve Android SDK location: honor existing env, then common paths
if [ -n "$ANDROID_HOME" ]; then
  ANDROID_HOME="$ANDROID_HOME"
elif [ -n "$ANDROID_SDK_ROOT" ]; then
  ANDROID_HOME="$ANDROID_SDK_ROOT"
else
  if [ -d "$HOME/Library/Android/sdk" ]; then
    ANDROID_HOME="$HOME/Library/Android/sdk"
  elif [ -d "$HOME/Android/Sdk" ]; then
    ANDROID_HOME="$HOME/Android/Sdk"
  else
    ANDROID_HOME="$HOME/.android-sdk"
  fi
fi
BITWARDEN_PKG="com.x8bit.bitwarden.dev"

echo === RUNNING setup_app_source.sh ===

# Define the APK path as an ABSOLUTE path from the project root.
# APK_PATH="$PROJECT_ROOT/codebase/app/build/outputs/apk/fdroid/debug/com.x8bit.bitwarden.dev-fdroid.apk"

echo "=== RUNNING setup_app_source.sh ==="
echo "[DEBUG] Project root is: $PROJECT_ROOT"

# Common directories used later
CODEBASE_DIR="$PROJECT_ROOT/codebase"
FDROID_DEBUG_APK_DIR="$CODEBASE_DIR/app/build/outputs/apk/fdroid/debug"
STANDARD_DEBUG_APK_DIR="$CODEBASE_DIR/app/build/outputs/apk/standard/debug"
FDROID_RELEASE_APK_DIR="$CODEBASE_DIR/app/build/outputs/apk/fdroid/release"

# Resolved APK path (absolute). Will be filled by resolve_apk_path()
APK_PATH=""
PREBUILT_CACHE_DIR="$PROJECT_ROOT/prebuilt-apk"

# 1. Create user.properties if missing
USER_PROPERTIES="codebase/user.properties"
if [ ! -f "$USER_PROPERTIES" ]; then
    echo "[INFO] Creating user.properties in codebase/"
    if [ -z "$GITHUB_TOKEN" ]; then
        read -p "Enter your GitHub Personal Access Token (with read:packages scope): " GITHUB_TOKEN
    else
        echo "[INFO] Using GITHUB_TOKEN from environment."
    fi
    echo "gitHubToken=$GITHUB_TOKEN" > "$USER_PROPERTIES"
    echo "localSdk=false" >> "$USER_PROPERTIES"
    echo "[INFO] user.properties created."
else
    echo "[INFO] user.properties already exists."
fi

# Move into codebase directory for build-related steps
cd "$CODEBASE_DIR"

# Check prerequisites
check_prerequisites() {
    echo "Checking prerequisites..."
    
    # Check Java availability
    if ! command -v java >/dev/null 2>&1; then
        echo "ERROR: Java not found. Please install Java 17 and ensure it is on PATH or set JAVA_HOME."
        exit 1
    fi
    JAVA_VERSION=$(java -version 2>&1 | awk -F[\"_] 'NR==1{print $2}')
    if [[ "$JAVA_VERSION" != 17* ]]; then
        echo "ERROR: Java 17 required. Found: $JAVA_VERSION. Please install and configure Java 17."
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
    if [ -z "$JAVA_HOME" ]; then
        if [[ "$OSTYPE" == "darwin"* ]]; then
            JAVA_HOME="$(/usr/libexec/java_home -v 17 2>/dev/null)"
        elif [ -d "/usr/lib/jvm/java-17-openjdk-amd64" ]; then
            JAVA_HOME="/usr/lib/jvm/java-17-openjdk-amd64"
        fi
    fi
    if [ -n "$JAVA_HOME" ]; then
        export JAVA_HOME
        export PATH="$JAVA_HOME/bin:$PATH"
    fi
    
    # Set Android SDK
    export ANDROID_HOME="$ANDROID_HOME"
    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
    
    # Create local.properties for Bitwarden build
    echo "sdk.dir=$ANDROID_HOME" > local.properties
    
    echo "Environment configured."
}

# Build Bitwarden APK with optimal settings for CI with an emulator
build_bitwarden() {
    echo "Building Bitwarden (Optimized for CI with Emulator)..."
    
    ./gradlew --stop
    
    # Memory settings are conservative to leave room for the emulator
    export GRADLE_OPTS="-Xmx3g -XX:MaxMetaspaceSize=512m -Dfile.encoding=UTF-8"
    export KOTLIN_DAEMON_JVMARGS="-Xmx1536m"
    
    # Use --max-workers=2 to perfectly match the 2 CPU cores of the CI runner
    ./gradlew --daemon --parallel --build-cache --max-workers=2 \
        :app:assembleFdroidDebug --console=plain -S
    
    echo "Build completed successfully."
}

# Resolve latest APK path across common output folders
resolve_apk_path() {
    local candidates=()
    # Prefer cached prebuilt APK copied by CI (outside submodule)
    if [ -f "$PREBUILT_CACHE_DIR/bitwarden.apk" ]; then
        candidates+=( "$PREBUILT_CACHE_DIR/bitwarden.apk" )
    fi
    if compgen -G "$FDROID_DEBUG_APK_DIR/*.apk" > /dev/null; then
        candidates+=( $(ls -t "$FDROID_DEBUG_APK_DIR"/*.apk 2>/dev/null) )
    fi
    if compgen -G "$STANDARD_DEBUG_APK_DIR/*.apk" > /dev/null; then
        candidates+=( $(ls -t "$STANDARD_DEBUG_APK_DIR"/*.apk 2>/dev/null) )
    fi
    if compgen -G "$FDROID_RELEASE_APK_DIR/*.apk" > /dev/null; then
        candidates+=( $(ls -t "$FDROID_RELEASE_APK_DIR"/*.apk 2>/dev/null) )
    fi

    if [ ${#candidates[@]} -gt 0 ]; then
        APK_PATH="${candidates[0]}"
    else
        APK_PATH=""
    fi
}

# A robust function to verify the APK exists with rich debugging
verify_apk_exists() {
    echo "[INFO] Verifying APK exists before installation..."
    echo "[DEBUG] Current working directory: $(pwd)"
    echo "[DEBUG] Checking for file: $APK_PATH"
    
    if [[ ! -f "$APK_PATH" ]]; then
        echo "------------------------------------------------------------"
        echo "[FATAL ERROR] APK file not found at the expected path."
        echo "------------------------------------------------------------"
        
        echo "[DIAGNOSTIC] Listing contents of the 'outputs' directory to debug..."
        if [ -d "$CODEBASE_DIR/app/build/outputs" ]; then
            ls -lR "$CODEBASE_DIR/app/build/outputs"
        else
            echo "[DIAGNOSTIC] The directory '$CODEBASE_DIR/app/build/outputs' does not exist. The build likely failed to produce any output."
        fi
        echo "------------------------------------------------------------"
        exit 1
    fi
    echo "[SUCCESS] APK file found!"
}


# Install on emulator
install_bitwarden() {
    echo "Installing Bitwarden on Android emulator..."
    
    if ! adb devices | grep -w "device" | grep -v "List" >/dev/null; then
        echo "ERROR: No Android emulator or device found."
        exit 1
    fi
    
    adb install -r "$APK_PATH"
    echo "Bitwarden installed successfully."
}

# Launch Bitwarden directly
launch_bitwarden() {
    echo "Launching Bitwarden..."
    
    adb shell monkey -p $BITWARDEN_PKG -c android.intent.category.LAUNCHER 1
    
    sleep 2
    if adb shell dumpsys window | grep -q "mCurrentFocus.*$BITWARDEN_PKG"; then
        echo "Successfully launched Bitwarden!"
        return 0
    else
        echo "Bitwarden may not have launched properly."
        return 1
    fi
}

# Main function with robust logic
main() {
    echo "Bitwarden Android Setup"
    echo "======================="
    
    check_prerequisites
    setup_environment

    # Try to resolve a prebuilt APK first
    resolve_apk_path
    if [ -n "$APK_PATH" ]; then
        echo "[INFO] Prebuilt APK found at: $APK_PATH. Skipping build."
    else
        echo "[INFO] No prebuilt APK found. Building now..."
        ls -lR "$CODEBASE_DIR/app/build/outputs/apk/fdroid/debug"
        build_bitwarden
        # Re-resolve after build
        resolve_apk_path
    fi

    verify_apk_exists
    
    install_bitwarden
    
    echo ""
    echo "=========================================="
    echo "Setup complete! Bitwarden has been installed."
    echo "=========================================="
    echo ""
    
    if launch_bitwarden; then
        echo "Bitwarden is now running and ready for mobile security testing!"
    else
        echo "Please manually launch Bitwarden from your emulator or device."
    fi
    
    echo ""
    echo "Bitwarden setup completed successfully!"
    echo === FINISHED setup_app_source.sh ===
}

# Run main function
main