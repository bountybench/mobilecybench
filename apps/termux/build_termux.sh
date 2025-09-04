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

if ! ./gradlew assembleDebug --no-daemon --max-workers=1 --stacktrace --info; then
    echo "ERROR: Gradle build failed!"
    echo "Checking build directory contents:"
    find . -name "*.apk" -type f 2>/dev/null || echo "No APK files found"
    echo "Checking build directories:"
    find . -name "build" -type d 2>/dev/null || echo "No build directories found"
    exit 1
fi

echo "Gradle build completed successfully!"
echo "Checking for APK files..."
find . -name "*.apk" -type f -ls 2>/dev/null || echo "No APK files found"

# Find the APK file (handle different possible locations)
APK=$(find . -path "*/build/outputs/apk/debug/*.apk" -type f | head -n1)
if [ -z "$APK" ]; then
    echo "ERROR: No APK produced after successful build"
    echo "Checking build directory contents:"
    find . -name "build" -type d -exec ls -la {} \; 2>/dev/null || echo "No build directories found"
    exit 1
fi

echo "Build successful! APK found: $APK"
echo "APK size: $(du -h "$APK" | cut -f1)"

# Copy APK to mounted volume for host access
cp "$APK" /app/termux-debug.apk
echo "APK copied to /app/termux-debug.apk for host access"

