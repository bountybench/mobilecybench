#!/bin/bash

# FairEmail Build from Source Script
# This script builds FairEmail from source code

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

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

print_status "Starting FairEmail build from source..."

# Check if we're in the right directory
if [ ! -d "codebase" ]; then
    print_error "codebase directory not found. Please ensure the FairEmail submodule is initialized."
    exit 1
fi

# Navigate to codebase directory
cd codebase

# Check if Java is available
if ! command -v java &> /dev/null; then
    print_error "Java not found. Please install Java 8 or higher."
    exit 1
fi

# Check Java version
JAVA_VERSION=$(java -version 2>&1 | head -1 | cut -d'"' -f2 | sed '/^1\./s///' | cut -d'.' -f1)
if [ "$JAVA_VERSION" -lt 8 ]; then
    print_error "Java 8 or higher is required. Found Java $JAVA_VERSION"
    exit 1
fi

print_success "Java $JAVA_VERSION detected"

# Check if Android SDK is available
if [ -z "$ANDROID_HOME" ] && [ -z "$ANDROID_SDK_ROOT" ]; then
    print_warning "ANDROID_HOME or ANDROID_SDK_ROOT not set. Trying to find Android SDK..."
    
    # Common Android SDK locations
    POSSIBLE_PATHS=(
        "$HOME/Android/Sdk"
        "$HOME/Library/Android/sdk"
        "/usr/local/android-sdk"
        "/opt/android-sdk"
    )
    
    for path in "${POSSIBLE_PATHS[@]}"; do
        if [ -d "$path" ]; then
            export ANDROID_HOME="$path"
            export ANDROID_SDK_ROOT="$path"
            print_success "Found Android SDK at: $path"
            break
        fi
    done
    
    if [ -z "$ANDROID_HOME" ]; then
        print_error "Android SDK not found. Please set ANDROID_HOME or ANDROID_SDK_ROOT environment variable."
        exit 1
    fi
else
    if [ -n "$ANDROID_HOME" ]; then
        export ANDROID_SDK_ROOT="$ANDROID_HOME"
    else
        export ANDROID_HOME="$ANDROID_SDK_ROOT"
    fi
    print_success "Using Android SDK at: $ANDROID_HOME"
fi

# Add Android SDK tools to PATH
export PATH="$ANDROID_HOME/tools:$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"

# Check if Gradle wrapper exists
if [ ! -f "gradlew" ]; then
    print_error "Gradle wrapper (gradlew) not found in FairEmail directory"
    exit 1
fi

# Make gradlew executable
chmod +x gradlew

# Clean previous builds
print_status "Cleaning previous builds..."
./gradlew clean

# Build the app
print_status "Building FairEmail (this may take several minutes)..."
print_status "Building Play Store variant..."

# Try to build the Play Store variant first
if ./gradlew :app:assemblePlayRelease; then
    print_success "Play Store variant built successfully!"
    APK_PATH="app/build/outputs/apk/play/release"
elif ./gradlew :app:assembleGithubRelease; then
    print_success "GitHub variant built successfully!"
    APK_PATH="app/build/outputs/apk/github/release"
    print_warning "Using GitHub variant instead of Play Store variant"
else
    print_error "Failed to build any variant"
    exit 1
fi

# Find the built APK
APK_FILE=$(find "$APK_PATH" -name "*.apk" -type f | head -1)

if [ -z "$APK_FILE" ] || [ ! -f "$APK_FILE" ]; then
    print_error "No APK found in $APK_PATH"
    exit 1
fi

print_success "APK built successfully: $APK_FILE"

# Display APK information
print_status "APK Information:"
ls -lh "$APK_FILE"

# Go back to parent directory
cd ..

print_success "FairEmail build completed successfully!"
print_status "APK location: $(pwd)/$APK_FILE"
