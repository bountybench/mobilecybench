#!/bin/bash
set -e

echo "Setting up Termux app source code..."

# Check if codebase submodule exists
if [ ! -d "codebase" ]; then
    echo "Error: codebase submodule not found"
    echo "Please run: git submodule update --init --recursive"
    exit 1
fi

cd codebase

# Make gradle wrapper executable
chmod +x gradlew

cd ..

# Build the Docker image + clean up any existing container
docker build --no-cache -t termux-builder .
docker rm -f termux-builder-temp 2>/dev/null || echo "No existing container to clean up"

# Run the build in Docker and copy APK 
CONTAINER_ID=$(docker run -d \
    --name termux-builder-temp \
    -v "$(pwd)/codebase:/codebase" \
    -v gradle-cache:/root/.gradle \
    termux-builder \
    /app/build_termux.sh)

echo "Waiting for build to complete..."
while docker inspect "$CONTAINER_ID" --format='{{.State.Status}}' 2>/dev/null | grep -q "running"; do
    sleep 10
done

# Check if container exited successfully
EXIT_CODE=$(docker inspect "$CONTAINER_ID" --format='{{.State.ExitCode}}')
echo "Container exit code: $EXIT_CODE"

if [ "$EXIT_CODE" -ne 0 ]; then
    echo "ERROR: Container exited with code $EXIT_CODE"
    echo "Container logs:"
    docker logs "$CONTAINER_ID"
    docker rm "$CONTAINER_ID" >/dev/null 2>&1 || true
    exit 1
fi

# Copy APK from container to host
echo "Copying APK from container..."
docker cp "$CONTAINER_ID":/app/termux-debug.apk ./termux-debug.apk

# Clean up container
docker rm "$CONTAINER_ID" >/dev/null 2>&1 || true

# Check if APK was copied successfully
if [ -f "termux-debug.apk" ]; then
    echo "Docker build successful! APK created: termux-debug.apk"
    echo "APK size: $(du -h termux-debug.apk | cut -f1)"
else
    echo "Docker build failed. APK not found."
    exit 1
fi

echo "Source code setup completed"
echo "APK built successfully and ready for installation"
echo "Requirements: Docker with Java 11, Android SDK API 34, Build Tools 34.0.0, NDK 21.4.7075529"
