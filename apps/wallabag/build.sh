#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

# MCB_OBFUSCATE is set by build_apk.sh --obfuscate. When on, forward the
# repo-level init script to gradlew so it can flip minifyEnabled on the
# release buildType (rename-only invariant; shrinkResources intentionally
# untouched) and append generated rename-only rules without touching the
# submodule's build.gradle.
GRADLE_ARGS=()
if [ "${MCB_OBFUSCATE:-0}" = "1" ] && [ -n "${MCB_OBFUSCATE_INIT_SCRIPT:-}" ]; then
    GRADLE_ARGS+=(--init-script "$MCB_OBFUSCATE_INIT_SCRIPT")
fi

./gradlew "${GRADLE_ARGS[@]}" clean
./gradlew "${GRADLE_ARGS[@]}" assembleRelease --no-daemon

cp app/build/outputs/apk/release/app-release-unsigned.apk "$SCRIPT_DIR/unsigned.apk"
