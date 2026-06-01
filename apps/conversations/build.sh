#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

GRADLE_ARGS=()
if [ "${MCB_OBFUSCATE:-0}" = "1" ] && [ -n "${MCB_OBFUSCATE_INIT_SCRIPT:-}" ]; then
    GRADLE_ARGS+=(--init-script "$MCB_OBFUSCATE_INIT_SCRIPT")
fi

./gradlew "${GRADLE_ARGS[@]}" clean
./gradlew "${GRADLE_ARGS[@]}" assembleConversationsFreeRelease --no-daemon

# Copy universal APK to standard location for root wrapper
cp build/outputs/apk/conversationsFree/release/*conversations-free*universal*release-unsigned.apk "$SCRIPT_DIR/unsigned.apk"
