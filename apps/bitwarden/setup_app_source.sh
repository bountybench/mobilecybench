#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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
# APK_PATH="app/build/outputs/apk/fdroid/release/com.x8bit.bitwarden-fdroid.apk"
APK_PATH="app/build/outputs/apk/fdroid/debug/com.x8bit.bitwarden.dev-fdroid.apk"

echo === RUNNING setup_app_source.sh ===

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

# Move into codebase directory for all subsequent steps
cd codebase

# Check prerequisites
check_prerequisites() {
    echo "Checking prerequisites..."
    
    # Install Python dependencies
    PIP_CMD=""
    if command -v pip3 >/dev/null 2>&1; then
        PIP_CMD="pip3"
    elif command -v pip >/dev/null 2>&1; then
        PIP_CMD="pip"
    fi

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
    
    # Set Java 17 (cross-platform resolution if JAVA_HOME is not set)
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

# Build Bitwarden APK
build_bitwarden() {
    echo "Building Bitwarden Android from source..."
    echo "This MAY take several minutes..."
    
    # Build Bitwarden APK (debug)
    ./gradlew --stop
    export GRADLE_OPTS="-Xmx1536m -XX:MaxMetaspaceSize=256m -Dfile.encoding=UTF-8"
    export KOTLIN_DAEMON_JVMARGS="-Xmx768m"
    ./gradlew --no-daemon --max-workers=1 -Dorg.gradle.parallel=false \
    :app:assembleFdroidDebug --console=plain
    
    echo "Build completed successfully."
}

# Install on emulator
install_bitwarden() {
    echo "Installing Bitwarden on Android emulator..."
    
    # Check if emulator is running
    if ! adb devices | grep -w "device" | grep -v "List" >/dev/null; then
        echo "ERROR: No Android emulator or device found."
        echo "Please start the emulator or connect a device first."
        exit 1
    fi
    
    if [[ ! -f $APK_PATH ]]; then
        echo "ERROR: APK not found at $APK_PATH"
        echo "Available APKs:"
        find app/build/outputs -name "*.apk" -type f 2>/dev/null | head -10
        exit 1
    fi
    
    adb install -r "$APK_PATH"
    echo "Bitwarden installed successfully."
}

# Launch Bitwarden directly
launch_bitwarden() {
    echo "Launching Bitwarden..."
    
    # Launch Bitwarden using package name
    adb shell monkey -p $BITWARDEN_PKG -c android.intent.category.LAUNCHER 1
    
    # Verify launch
    sleep 2
    if adb shell dumpsys window | grep -q "mCurrentFocus.*$BITWARDEN_PKG"; then
        echo "Successfully launched Bitwarden!"
        return 0
    else
        echo "Bitwarden may not have launched properly."
        echo "Please check your emulator or device - Bitwarden should be installed."
        return 1
    fi
}

# Main function
main() {
    echo "Bitwarden Android Setup"
    echo "======================="
    
    echo "Setting up Bitwarden Android"
    
    check_prerequisites
    setup_environment

    CANDIDATES=$(ls -l app/build/outputs/apk/fdroid/debug/*.apk)
    echo "CANDIDATES in app/build/outputs/apk/fdroid/debug: $CANDIDATES"

    # In main(), before build_bitwarden
    if compgen -G "$SCRIPT_DIR/codebase/app/build/outputs/apk/fdroid/debug/*.apk" > /dev/null; then
        APK_PATH="$(ls -t app/build/outputs/apk/fdroid/debug/*.apk | head -n 1)"
        echo "[INFO] Prebuilt APK found at: $APK_PATH"
    else
        echo "[INFO] No prebuilt APK found."
        APK_PATH="$(ls -t app/build/outputs/apk/fdroid/debug/*.apk | head -n 1)"
        echo "APK_PATH: $APK_PATH"
        build_bitwarden
    fi

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
        echo "You can also try running: adb shell monkey -p $BITWARDEN_PKG -c android.intent.category.LAUNCHER 1"
    fi
    
    echo ""
    echo "Bitwarden setup completed successfully!"
    echo === FINISHED setup_app_source.sh ===
}

# Run main function
main 