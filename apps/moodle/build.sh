#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Build using Docker
docker build --platform linux/amd64 -t moodle-builder -f Dockerfile.android .

# Extract APK from container
docker rm -f temp-builder 2>/dev/null || true
docker create --name temp-builder moodle-builder
docker cp temp-builder:/moodleapp/platforms/android/app/build/outputs/apk/release/app-release-unsigned.apk "$SCRIPT_DIR/unsigned.apk"
docker rm temp-builder
