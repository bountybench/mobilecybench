#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

if [[ -f "gradle.properties" ]]; then
    sed -i.bak '/^org\.gradle\.jvmargs=/d' gradle.properties
    sed -i.bak '/^org\.gradle\.configuration-cache=/d' gradle.properties
    echo "org.gradle.jvmargs=-Xmx4g" >> gradle.properties
    echo "org.gradle.configuration-cache=false" >> gradle.properties
fi

if [[ -f "mobile/build.gradle" ]]; then
    cp mobile/build.gradle mobile/build.gradle.bak
    perl -0pi -e 's|implementation "com\.github\.chimbori:colorpicker:0\.1\.1"|implementation files("\$rootDir/../deps/colorpicker-0.1.1.aar")|g; s|implementation "com\.github\.AppIntro:AppIntro:6\.3\.1"|implementation files("\$rootDir/../deps/AppIntro-6.3.1.aar")|g; s|implementation "com\.github\.chrisbanes:PhotoView:2\.3\.0"|implementation files("\$rootDir/../deps/PhotoView-2.3.0.aar")|g; s|implementation "com\.github\.daniel-stoneuk:material-about-library:3\.1\.2"|implementation files("\$rootDir/../deps/material-about-library-3.1.2.aar")|g' mobile/build.gradle
fi

./gradlew :mobile:clean :mobile:assembleFullStableRelease --no-daemon -x lint -x lintVitalFullStableRelease -x uploadCrashlyticsMappingFileFullStableRelease

APK_PATH=$(find mobile/build/outputs/apk -type f \( -name "*release.apk" -o -name "*release-unsigned.apk" \) 2>/dev/null | head -1)

cp "$APK_PATH" "$SCRIPT_DIR/unsigned.apk"

if [[ -f "gradle.properties.bak" ]]; then
    mv gradle.properties.bak gradle.properties
fi

if [[ -f "mobile/build.gradle.bak" ]]; then
    mv mobile/build.gradle.bak mobile/build.gradle
fi
