#!/bin/bash
set -e

echo "Building Termux APK in Docker container..."

# Check if codebase is mounted
if [ ! -d "/codebase" ]; then
    echo "Error: codebase directory not mounted"
    echo "Expected: /codebase (mounted from host)"
    exit 1
fi

cd /codebase

# Make gradle wrapper executable
chmod +x gradlew

echo "Verifying Android SDK components..."
if [ ! -d "$ANDROID_HOME/platforms/android-34" ]; then
    echo "Error: Android API 34 not found"
    exit 1
fi

if [ ! -d "$ANDROID_NDK_HOME" ]; then
    echo "Error: NDK 21.4.7075529 not found"
    exit 1
fi

# Clean any previous builds
./gradlew clean --no-daemon || true

# Build the APK
echo "Starting Gradle build..."
./gradlew assembleDebug --no-daemon --max-workers=1 -Pandroid.injected.abi=arm64-v8a --info

# Check if build was successful
if [ -f "app/build/outputs/apk/debug/app-arm64-v8a-debug.apk" ]; then
    echo "Build successful! APK created: app/build/outputs/apk/debug/app-arm64-v8a-debug.apk"
    echo "APK size: $(du -h app/build/outputs/apk/debug/app-arm64-v8a-debug.apk | cut -f1)"
    
    # Copy APK to mounted volume for host access
    cp app/build/outputs/apk/debug/app-arm64-v8a-debug.apk /app/termux-debug.apk
    echo "APK copied to /app/termux-debug.apk for host access"
    
elif [ -f "app/build/outputs/apk/debug/app-debug.apk" ]; then
    echo "Build successful! APK created: app/build/outputs/apk/debug/app-debug.apk"
    echo "APK size: $(du -h app/build/outputs/apk/debug/app-debug.apk | cut -f1)"
    
    # Copy APK to mounted volume for host access
    cp app/build/outputs/apk/debug/app-debug.apk /app/termux-debug.apk
    echo "APK copied to /app/termux-debug.apk for host access"
    
else
    echo "Build failed. APK not found."
    echo "Checking build directory contents:"
    ls -la app/build/outputs/apk/debug/ 2>/dev/null || echo "Build directory not found"
    exit 1
fi

