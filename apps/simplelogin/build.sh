#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase/SimpleLogin"

# Use debug signing (gradle provides internally) - app hardcodes keystore path
sed -i.bak 's/signingConfig signingConfigs.release/signingConfig signingConfigs.debug/' app/build.gradle

# MCB_OBFUSCATE is set by build_apk.sh --obfuscate. When on, forward the
# repo-level init script to gradlew so it can flip minifyEnabled/shrinkResources
# on the release buildType without touching the submodule's build.gradle. The
# absence of this forwarding is the slackdump "fake-obfuscation" trap; the
# top-level build_apk.sh hard-refuses --obfuscate unless this file references
# MCB_OBFUSCATE_INIT_SCRIPT.
GRADLE_ARGS=()
if [ "${MCB_OBFUSCATE:-0}" = "1" ] && [ -n "${MCB_OBFUSCATE_INIT_SCRIPT:-}" ]; then
    GRADLE_ARGS+=(--init-script "$MCB_OBFUSCATE_INIT_SCRIPT")
fi

./gradlew "${GRADLE_ARGS[@]}" --no-daemon assembleFdroidRelease

cp app/build/outputs/apk/fdroid/release/*.apk "$SCRIPT_DIR/unsigned.apk"
