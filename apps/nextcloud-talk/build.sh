#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

# CI sets GRADLE_OPTS with -Dkotlin.daemon.jvm.options=-Xmx2g which starves kapt.
# Override to give Kotlin daemon 3GB. Runner has 7GB total; Gradle build JVM gets
# 4GB (from gradle.properties), Kotlin daemon gets 3GB — they don't peak simultaneously.
export GRADLE_OPTS="-Xmx2g -Dkotlin.daemon.jvm.options=-Xmx3g"
./gradlew clean packageGenericReleaseUniversalApk --no-daemon --dependency-verification=off \
    -x lintVitalGenericRelease -x lintVitalAnalyzeGenericRelease -x lintVitalReportGenericRelease -x generateGenericReleaseLintVitalReportModel

cp app/build/outputs/apk_from_bundle/genericRelease/*-generic-release-universal-unsigned.apk "$SCRIPT_DIR/unsigned.apk"
# TEMP cache-validation marker: revert before merge (PR #1021)
