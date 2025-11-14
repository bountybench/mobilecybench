#!/bin/bash

# FairEmail Setup Script
# This script sets up the environment and installs FairEmail on an Android emulator

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

# Check if we're in the right directory
if [ ! -f "setup_app_source.sh" ]; then
    print_error "setup_app_source.sh not found. Please run this script from the BAIR-APPS directory."
    exit 1
fi

print_status "Starting FairEmail setup..."

# Check if Android SDK is available
if ! command -v adb &> /dev/null; then
    print_error "ADB not found. Please install Android SDK and add it to your PATH."
    exit 1
fi

# Check if emulator is running
print_status "Checking for running Android emulator..."
if ! adb devices | grep -q "emulator"; then
    print_warning "No Android emulator detected. Please start an emulator first."
    print_status "You can start an emulator using: emulator -avd <avd_name>"
    read -p "Press Enter when your emulator is running..."
fi

# Verify emulator is accessible
if ! adb shell echo "test" &> /dev/null; then
    print_error "Cannot connect to Android emulator. Please ensure it's running and accessible."
    exit 1
fi

print_success "Android emulator detected and accessible"

# Build the app from source
print_status "Building FairEmail from source..."
if [ -f "setup_app_source.sh" ]; then
    chmod +x setup_app_source.sh
    ./setup_app_source.sh
else
    print_error "setup_app_source.sh not found"
    exit 1
fi

# Find the APK (prefer apk/ directory, fallback to build directory)
APK_PATH=""
if [ -d "apk" ] && [ -n "$(find apk -maxdepth 1 -name "*.apk" -type f 2>/dev/null)" ]; then
    # Use APK from apk/ directory (preferred location for CI)
    APK_PATH=$(find apk -maxdepth 1 -name "*.apk" -type f | head -1)
    print_status "Found APK in apk/ directory: $APK_PATH"
elif [ -f "codebase/app/build/outputs/apk/play/release/FairEmail-v1.2300a-play-release.apk" ]; then
    APK_PATH="codebase/app/build/outputs/apk/play/release/FairEmail-v1.2300a-play-release.apk"
elif [ -f "codebase/app/build/outputs/apk/github/release/FairEmail-v1.2300a-github-release.apk" ]; then
    APK_PATH="codebase/app/build/outputs/apk/github/release/FairEmail-v1.2300a-github-release.apk"
else
    # Try to find any APK in the outputs directory
    APK_PATH=$(find codebase/app/build/outputs/apk -name "*.apk" -type f 2>/dev/null | head -1)
fi

if [ -z "$APK_PATH" ] || [ ! -f "$APK_PATH" ]; then
    print_error "No APK found. Build may have failed or APK not in expected location."
    exit 1
fi

print_success "Found APK: $APK_PATH"

# Install the APK on the emulator
print_status "Installing FairEmail on emulator..."
if adb install -r "$APK_PATH"; then
    print_success "FairEmail installed successfully!"
else
    print_error "Failed to install APK on emulator"
    exit 1
fi

# Launch the app
print_status "Launching FairEmail..."
adb shell am start -n eu.faircode.email/.ui.ActivityMain

print_success "Setup complete! FairEmail should now be running on your emulator."
print_status "You can find the app in your emulator's app drawer."
