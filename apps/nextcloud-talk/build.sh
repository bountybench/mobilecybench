#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

# CI sets GRADLE_OPTS with -Dkotlin.daemon.jvm.options=-Xmx2g which starves kapt.
# Override to give Kotlin daemon 3GB. Runner has 7GB total; Gradle build JVM gets
# 4GB (from gradle.properties), Kotlin daemon gets 3GB — they don't peak simultaneously.
export GRADLE_OPTS="-Xmx2g -Dkotlin.daemon.jvm.options=-Xmx3g"

# MCB_OBFUSCATE is set by build_apk.sh --obfuscate. Forward the repo-level
# init script so R8 minify/shrink is enabled without editing upstream Gradle.
GRADLE_ARGS=()
if [ "${MCB_OBFUSCATE:-0}" = "1" ] && [ -n "${MCB_OBFUSCATE_INIT_SCRIPT:-}" ]; then
    GRADLE_ARGS+=(--init-script "$MCB_OBFUSCATE_INIT_SCRIPT")
fi

./gradlew "${GRADLE_ARGS[@]}" clean packageGenericReleaseUniversalApk --no-daemon --dependency-verification=off \
    -x lintVitalGenericRelease -x lintVitalAnalyzeGenericRelease -x lintVitalReportGenericRelease -x generateGenericReleaseLintVitalReportModel

cp app/build/outputs/apk_from_bundle/genericRelease/*-generic-release-universal-unsigned.apk "$SCRIPT_DIR/unsigned.apk"
