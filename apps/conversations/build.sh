#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

./gradlew clean
./gradlew assembleConversationsFreeRelease --no-daemon

# Copy universal APK to standard location for root wrapper
cp build/outputs/apk/conversationsFree/release/*conversations-free*universal*release-unsigned.apk "$SCRIPT_DIR/unsigned.apk"
