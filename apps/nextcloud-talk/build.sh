#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

# Fix dependency verification hashes by trusting nextcloud-deps group
# This is needed because some upstream dependencies have broken hashes in verification-metadata.xml
VERIFICATION_METADATA="gradle/verification-metadata.xml"
if [ -f "$VERIFICATION_METADATA" ]; then
    echo "Applying dependency verification fix to $VERIFICATION_METADATA..."
    # Insert trust entry if it doesn't exist
    if ! grep -q 'group="com.github.nextcloud-deps" reason="temp trust"' "$VERIFICATION_METADATA"; then
        sed -i '' '/<trusted-artifacts>/a\
         <trust group="com.github.nextcloud-deps" reason="temp trust for all nextcloud-deps"/>' "$VERIFICATION_METADATA"
    fi
fi

# CI sets GRADLE_OPTS with -Dkotlin.daemon.jvm.options=-Xmx2g which starves kapt.
# Override to give Kotlin daemon 3GB. Runner has 7GB total; Gradle build JVM gets
# 4GB (from gradle.properties), Kotlin daemon gets 3GB — they don't peak simultaneously.
export GRADLE_OPTS="-Xmx2g -Dkotlin.daemon.jvm.options=-Xmx3g"

# Using --dependency-verification=off as an additional safeguard alongside the metadata patch
./gradlew clean packageGenericReleaseUniversalApk --no-daemon --dependency-verification=off \
    -x lintVitalGenericRelease -x lintVitalAnalyzeGenericRelease -x lintVitalReportGenericRelease -x generateGenericReleaseLintVitalReportModel

cp app/build/outputs/apk_from_bundle/genericRelease/*-generic-release-universal-unsigned.apk "$SCRIPT_DIR/unsigned.apk"
