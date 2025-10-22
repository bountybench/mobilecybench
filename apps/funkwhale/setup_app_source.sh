#!/bin/bash

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODEBASE_DIR="$SCRIPT_DIR/codebase"

# Android SDK location (check common locations)
if [ -d "$HOME/Library/Android/sdk" ]; then
    ANDROID_HOME="$HOME/Library/Android/sdk"
elif [ -d "$HOME/Android/Sdk" ]; then
    ANDROID_HOME="$HOME/Android/Sdk"
elif [ -n "$ANDROID_SDK_ROOT" ]; then
    ANDROID_HOME="$ANDROID_SDK_ROOT"
else
    ANDROID_HOME="$HOME/Library/Android/sdk"
fi

export ANDROID_HOME

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to verify Java 17 is active
verify_java17() {
    print_status "Verifying Java 17 is active..."

    if command_exists java; then
        CURRENT_JAVA_VER=$(java -version 2>&1 | head -1 | cut -d'"' -f2 | sed 's/^1\.//' | cut -d'.' -f1)
        print_status "Current Java version: $CURRENT_JAVA_VER"
        print_status "JAVA_HOME: $JAVA_HOME"

        if [ "$CURRENT_JAVA_VER" = "17" ]; then
            print_success "Java 17 is active and ready for build"
            return 0
        else
            print_error "Java $CURRENT_JAVA_VER is active, but Java 17 is required"
            return 1
        fi
    else
        print_error "Java command not found after setup"
        return 1
    fi
}

# Function to check Android SDK
check_android_sdk() {
    print_status "Checking Android SDK installation..."
    
    if [ -d "$ANDROID_HOME" ] && [ -f "$ANDROID_HOME/platform-tools/adb" ]; then
        print_success "Android SDK found at $ANDROID_HOME"
        return 0
    else
        print_warning "Android SDK not found at $ANDROID_HOME"
        return 1
    fi
}

# Function to check Android project structure
check_android_project() {
    print_status "Checking Android project structure..."

    if [ ! -d "$CODEBASE_DIR" ]; then
        print_error "Codebase directory not found: $CODEBASE_DIR"
        return 1
    fi

    cd "$CODEBASE_DIR"

    # Check for Android project files
    if [ -f "app/build.gradle.kts" ] && [ -f "gradlew" ]; then
        print_success "Found Funkwhale Android project with Kotlin DSL"
        return 0
    elif [ -f "app/build.gradle" ] && [ -f "gradlew" ]; then
        print_success "Found Funkwhale Android project with Groovy DSL"
        return 0
    else
        print_error "Invalid Android project structure"
        print_status "Expected: app/build.gradle(.kts) and gradlew"
        return 1
    fi
}

# Function to setup gradle wrapper
setup_gradle() {
    print_status "Setting up Gradle..."
    cd "$PROJECT_DIR"
    
    # Make gradlew executable
    chmod +x gradlew
    
    # Check gradle version
    ./gradlew --version
    
    print_success "Gradle wrapper configured"
}

# Function to create local.properties
create_local_properties() {
    print_status "Creating local.properties file..."
    cd "$CODEBASE_DIR"

    cat > local.properties << EOF
# Android SDK location
sdk.dir=$ANDROID_HOME

# NDK location (if needed)
ndk.dir=$ANDROID_HOME/ndk/25.1.8937393
EOF

    print_success "local.properties created"
}

# Function to fix ProGuard rules for R8 issues
fix_proguard_rules() {
    print_status "Updating ProGuard rules to fix R8 missing classes..."
    cd "$CODEBASE_DIR"

    PROGUARD_FILE="app/proguard-rules.pro"

    # Check if the file needs the OkHttp/Conscrypt rules
    if ! grep -q "org.conscrypt" "$PROGUARD_FILE" 2>/dev/null; then
        print_status "Adding OkHttp/Conscrypt rules to proguard-rules.pro..."

        # Append the necessary rules
        cat >> "$PROGUARD_FILE" << 'EOF'

# OkHttp and Conscrypt rules to fix R8 missing classes
-dontwarn org.conscrypt.**
-dontwarn okhttp3.internal.platform.**
-keep class org.conscrypt.** { *; }

# OkHttp platform used only on JVM and when Conscrypt dependency is available.
-dontwarn okhttp3.internal.platform.ConscryptPlatform
-dontwarn org.conscrypt.ConscryptHostnameVerifier

# Additional OkHttp rules
-keepnames class okhttp3.internal.publicsuffix.PublicSuffixDatabase
-dontwarn org.codehaus.mojo.animal_sniffer.*
-dontwarn okhttp3.internal.platform.AndroidPlatform
EOF
        print_success "ProGuard rules updated"
    else
        print_status "ProGuard rules already contain OkHttp/Conscrypt fixes"
    fi
}

# Function to sign APK with debug keystore (in-place signing)
sign_apk() {
    local apk_file="$1"
    print_status "Signing APK in-place for installation..."
    print_status "APK: $apk_file"

    # Default debug keystore location
    local debug_keystore="$HOME/.android/debug.keystore"

    # Check if debug keystore exists, create if not
    if [ ! -f "$debug_keystore" ]; then
        print_status "Creating debug keystore at: $debug_keystore"
        mkdir -p "$HOME/.android"

        # Generate debug keystore with default parameters
        if command_exists keytool; then
            print_status "Generating keystore with keytool..."
            if keytool -genkey -v -keystore "$debug_keystore" \
                -alias androiddebugkey \
                -storepass android \
                -keypass android \
                -keyalg RSA \
                -keysize 2048 \
                -validity 10000 \
                -dname "CN=Android Debug,O=Android,C=US" 2>&1; then
                print_success "Debug keystore created"
            else
                print_error "Failed to create debug keystore"
                return 1
            fi
        else
            print_error "keytool not found - cannot create debug keystore"
            return 1
        fi
    else
        print_status "Using existing debug keystore: $debug_keystore"
    fi

    # Sign the APK in place (overwrite original)
    if [ -n "$ANDROID_HOME" ]; then
        local apksigner_paths=("$ANDROID_HOME"/build-tools/*/apksigner)
        if [ -f "${apksigner_paths[0]}" ]; then
            local apksigner_path="${apksigner_paths[0]}"
            print_status "Signing APK with apksigner: $apksigner_path"

            if "$apksigner_path" sign \
                --ks "$debug_keystore" \
                --ks-pass pass:android \
                --key-pass pass:android \
                "$apk_file" 2>&1; then

                print_success "APK signed successfully with apksigner"
                echo "$apk_file"
                return 0
            else
                print_error "apksigner failed to sign APK"
                return 1
            fi
        else
            print_error "apksigner not found in Android SDK"
            return 1
        fi
    else
        print_error "ANDROID_HOME not set - cannot use apksigner"
        return 1
    fi
}

# Function to build APK
build_apk() {
     print_status "Building Funkwhale Android APK..."
    cd "$CODEBASE_DIR"

    # Add Gson ProGuard rules to fix TypeToken errors
    print_status "Adding Gson ProGuard rules..."
    cat >> app/proguard-rules.pro << 'EOF'

# Gson rules - preserve generic signatures for TypeToken
-keepattributes Signature
-keepattributes *Annotation*
-dontwarn sun.misc.**
-keep class com.google.gson.** { *; }
-keep class * extends com.google.gson.TypeAdapter
-keep class * implements com.google.gson.TypeAdapterFactory
-keep class * implements com.google.gson.JsonSerializer
-keep class * implements com.google.gson.JsonDeserializer
-keepclassmembers,allowobfuscation class * {
  @com.google.gson.annotations.SerializedName <fields>;
}
EOF

    # Build release APK (preferred for security testing)
    print_status "Building release APK..."

    # Build with --no-daemon to avoid daemon issues
    print_status "Attempting release build with --no-daemon flag..."
    if ./gradlew clean assembleRelease --no-daemon; then
        # Look for release APK
        RELEASE_APK=$(find app/build/outputs/apk -name "*release*.apk" | head -1)
        if [ -n "$RELEASE_APK" ] && [ -f "$RELEASE_APK" ]; then
            print_status "Found unsigned release APK: $RELEASE_APK"

            # Sign the APK in place with debug keystore for testing
            if sign_apk "$RELEASE_APK"; then
                APK_SIZE=$(du -h "$RELEASE_APK" | cut -f1)
                print_success "Release APK signed successfully!"
                print_status "APK location: $CODEBASE_DIR/$RELEASE_APK"
                print_status "APK size: $APK_SIZE"

                # Get package info if aapt is available
                if command_exists aapt; then
                    PACKAGE_NAME=$(aapt dump badging "$RELEASE_APK" 2>/dev/null | grep "package: name" | cut -d"'" -f2 || echo "unknown")
                    VERSION_NAME=$(aapt dump badging "$RELEASE_APK" 2>/dev/null | grep "versionName" | cut -d"'" -f4 || echo "unknown")
                    print_status "Package: $PACKAGE_NAME"
                    print_status "Version: $VERSION_NAME"
                fi
            else
                print_error "Failed to sign release APK"
                return 1
            fi
        else
            print_error "No release APK found after build"
            return 1
        fi
    else
        print_error "Release build failed"
        print_status "Only release builds are supported"
        return 1
    fi
}


# Function to show next steps
show_next_steps() {
    print_success "Funkwhale Android APK build completed!"
    echo ""

    # Copy APKs to standardized location
    print_status "Copying APKs to apps/funkwhale/apk/ directory..."

    # Create apk directory in script's directory (apps/funkwhale/apk/)
    APK_DIR="$SCRIPT_DIR/apk"
    mkdir -p "$APK_DIR"

    # Find and copy all built APK files
    APK_COUNT=0
    find "$CODEBASE_DIR" -name "*.apk" -type f 2>/dev/null | while read apk; do
        APK_NAME=$(basename "$apk")
        cp "$apk" "$APK_DIR/$APK_NAME"
        APK_SIZE=$(du -h "$APK_DIR/$APK_NAME" | cut -f1)
        echo "  Copied: $APK_DIR/$APK_NAME ($APK_SIZE)"
        APK_COUNT=$((APK_COUNT + 1))
    done

    if [ $APK_COUNT -gt 0 ]; then
        print_success "APK files copied to: $APK_DIR"
    else
        print_warning "No APK files found to copy"
    fi
    echo ""

    # Show built APK files in new location
    echo -e "${YELLOW}APK files available at apps/funkwhale/apk/:${NC}"
    find "$APK_DIR" -name "*.apk" -type f 2>/dev/null | while read apk; do
        APK_SIZE=$(du -h "$apk" | cut -f1)
        echo "  $apk ($APK_SIZE)"
    done
}

# Main execution
main() {
    print_status "Starting Funkwhale Android APK build..."
    print_status "Working with codebase at: $CODEBASE_DIR"
    echo ""

    # Verify Java 17 is actually active
    if ! verify_java17; then
        print_error "Java 17 setup verification failed"
        exit 1
    fi

    if ! check_android_sdk; then
        print_error "Android SDK not found at: $ANDROID_HOME"
        print_error "Please run the main MobileCybench setup.sh first to install Android SDK"
        exit 1
    fi

    # Check project structure
    if ! check_android_project; then
        print_error "Invalid Android project structure in codebase directory"
        exit 1
    fi

    # Setup build environment
    create_local_properties
    setup_gradle

    # Fix ProGuard rules to prevent R8 issues
    fix_proguard_rules

    # Build APK
    build_apk

    # Show results
    show_next_steps

    print_success "Funkwhale Android APK build completed successfully!"
}

# Run main function
main "$@"
