#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

git submodule update --init --recursive

# Forward the repo-level gradle init script when build_apk.sh --obfuscate is in
# play. The init script auto-detects this app's upstream `minifyEnabled true`
# on release and leaves the tested release configuration alone.
GRADLE_ARGS=()
if [ "${MCB_OBFUSCATE:-0}" = "1" ] && [ -n "${MCB_OBFUSCATE_INIT_SCRIPT:-}" ]; then
    GRADLE_ARGS+=(--init-script "$MCB_OBFUSCATE_INIT_SCRIPT")
fi

./gradlew "${GRADLE_ARGS[@]}" clean
./gradlew "${GRADLE_ARGS[@]}" assembleRelease --no-daemon

cp app/build/outputs/apk/release/*-release-unsigned.apk "$SCRIPT_DIR/unsigned.apk"
