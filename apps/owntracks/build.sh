#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase/project"

GRADLE_ARGS=()
if [ "${MCB_OBFUSCATE:-0}" = "1" ] && [ -n "${MCB_OBFUSCATE_INIT_SCRIPT:-}" ]; then
    GRADLE_ARGS+=(--init-script "$MCB_OBFUSCATE_INIT_SCRIPT")
fi

./gradlew "${GRADLE_ARGS[@]}" :app:assembleOssRelease --no-daemon

cp app/build/outputs/apk/oss/release/*-release-unsigned.apk "$SCRIPT_DIR/unsigned.apk"
