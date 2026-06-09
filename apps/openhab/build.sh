#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

# MCB_OBFUSCATE is set by build_apk.sh --obfuscate. OpenHAB's release
# buildType already enables R8, but its proguard-rules.pro deliberately keeps
# readable upstream crash traces via -dontobfuscate. For benchmark obfuscated
# builds, remove that directive before Gradle configures R8 so app classes are
# actually renamed.
#
# Android manifest components are emitted as generated R8 -keep rules. The
# previous "obfuscated" OpenHAB APK exposed BackgroundTasksManager in
# cleartext, so give that manifest receiver an app-specific short source alias
# during obfuscated builds. The trap below restores the checkout after the APK
# is produced.
GRADLE_ARGS=()
if [ "${MCB_OBFUSCATE:-0}" = "1" ] && [ -n "${MCB_OBFUSCATE_INIT_SCRIPT:-}" ]; then
    GRADLE_ARGS+=(--init-script "$MCB_OBFUSCATE_INIT_SCRIPT")
fi

OPENHAB_OBF_BACKUP_DIR=""

backup_openhab_source_file() {
    local file="$1"
    if [ -z "$OPENHAB_OBF_BACKUP_DIR" ]; then
        OPENHAB_OBF_BACKUP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/openhab-obfuscate.XXXXXX")"
    fi
    mkdir -p "$OPENHAB_OBF_BACKUP_DIR/$(dirname "$file")"
    cp "$file" "$OPENHAB_OBF_BACKUP_DIR/$file"
}

restore_openhab_build_files() {
    if [ -n "$OPENHAB_OBF_BACKUP_DIR" ] && [ -d "$OPENHAB_OBF_BACKUP_DIR" ]; then
        while IFS= read -r backup; do
            rel="${backup#$OPENHAB_OBF_BACKUP_DIR/}"
            cp "$backup" "$rel"
        done < <(find "$OPENHAB_OBF_BACKUP_DIR" -type f)
        rm -rf "$OPENHAB_OBF_BACKUP_DIR"
    fi
    if [[ -f "gradle.properties.bak" ]]; then
        mv gradle.properties.bak gradle.properties
    fi
    if [[ -f "mobile/build.gradle.bak" ]]; then
        mv mobile/build.gradle.bak mobile/build.gradle
    fi
    if [[ -f "mobile/proguard-rules.pro.bak" ]]; then
        mv mobile/proguard-rules.pro.bak mobile/proguard-rules.pro
    fi
}

trap restore_openhab_build_files EXIT

if [[ -f "gradle.properties" ]]; then
    cp gradle.properties gradle.properties.bak
    perl -0pi -e 's/^org\.gradle\.jvmargs=.*\R//mg; s/^org\.gradle\.configuration-cache=.*\R//mg' gradle.properties
    echo "org.gradle.jvmargs=-Xmx4g" >> gradle.properties
    echo "org.gradle.configuration-cache=false" >> gradle.properties
fi

if [[ -f "mobile/build.gradle" ]]; then
    cp mobile/build.gradle mobile/build.gradle.bak
    perl -0pi -e 's|implementation "com\.github\.chimbori:colorpicker:0\.1\.1"|implementation files("\$rootDir/../deps/colorpicker-0.1.1.aar")|g; s|implementation "com\.github\.AppIntro:AppIntro:6\.3\.1"|implementation files("\$rootDir/../deps/AppIntro-6.3.1.aar")|g; s|implementation "com\.github\.chrisbanes:PhotoView:2\.3\.0"|implementation files("\$rootDir/../deps/PhotoView-2.3.0.aar")|g; s|implementation "com\.github\.daniel-stoneuk:material-about-library:3\.1\.2"|implementation files("\$rootDir/../deps/material-about-library-3.1.2.aar")|g' mobile/build.gradle
fi

if [ "${MCB_OBFUSCATE:-0}" = "1" ] && [[ -f "mobile/proguard-rules.pro" ]]; then
    cp mobile/proguard-rules.pro mobile/proguard-rules.pro.bak
    perl -0pi -e 's/^[ \t]*-dontobfuscate(?:[ \t]+#.*)?\R//mg' mobile/proguard-rules.pro
    if grep -qE '^[[:space:]]*-dontobfuscate([[:space:]]|$)' mobile/proguard-rules.pro; then
        echo "Failed to remove -dontobfuscate from mobile/proguard-rules.pro" >&2
        exit 1
    fi

    renamed_background_tasks_manager=0
    while IFS= read -r file; do
        backup_openhab_source_file "$file"
        perl -0pi -e 's/\bBackgroundTasksManager\b/A/g' "$file"
        renamed_background_tasks_manager=$((renamed_background_tasks_manager + 1))
    done < <(grep -rl 'BackgroundTasksManager' mobile/src/main/AndroidManifest.xml mobile/src/main/java 2>/dev/null || true)
    if [ "$renamed_background_tasks_manager" -eq 0 ]; then
        echo "Failed to find BackgroundTasksManager sources for OpenHAB obfuscation alias" >&2
        exit 1
    fi
fi

./gradlew "${GRADLE_ARGS[@]}" :mobile:clean :mobile:assembleFullStableRelease --no-daemon -x lint -x lintVitalFullStableRelease -x uploadCrashlyticsMappingFileFullStableRelease

APK_PATH=$(find mobile/build/outputs/apk -type f \( -name "*release.apk" -o -name "*release-unsigned.apk" \) 2>/dev/null | head -1)

cp "$APK_PATH" "$SCRIPT_DIR/unsigned.apk"
