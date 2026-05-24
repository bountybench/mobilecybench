#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

LOCAL_QP_AAR="$SCRIPT_DIR/deps/QuickPermissions-Kotlin-1.1.5.aar"
if [[ ! -f "$LOCAL_QP_AAR" ]]; then
    echo "[build.sh] ERROR: missing vendored dependency: $LOCAL_QP_AAR"
    exit 1
fi

# Make build deterministic in CI: use vendored QuickPermissions AAR and avoid JitPack.
sed -i.bak \
    -e '/jitpack\.io/d' \
    settings.gradle.kts

sed -i.bak \
    -e 's|implementation("com.github.cyb3rko:QuickPermissions-Kotlin:1.1.5")|implementation(files("${rootProject.projectDir}/../deps/QuickPermissions-Kotlin-1.1.5.aar"))|' \
    app/build.gradle.kts

GRADLE_ARGS=()
if [ "${MCB_OBFUSCATE:-0}" = "1" ] && [ -n "${MCB_OBFUSCATE_INIT_SCRIPT:-}" ]; then
    GRADLE_ARGS+=(--init-script "$MCB_OBFUSCATE_INIT_SCRIPT")
fi

./gradlew "${GRADLE_ARGS[@]}" --no-daemon --max-workers=1 :app:assembleRelease -x test -x lint -x check

APK_PATH=$(find . -type f -path "*/build/outputs/apk/**/release/*-universal-*.apk" 2>/dev/null | head -1)
if [[ -z "$APK_PATH" ]]; then
    APK_PATH=$(find . -type f -path "*/build/outputs/apk/**/release/*arm64-v8a*-release.apk" 2>/dev/null | head -1)
fi
if [[ -z "$APK_PATH" ]]; then
    APK_PATH=$(find . -type f -path "*/build/outputs/apk/**/release/*-release.apk" 2>/dev/null | head -1)
fi
if [[ -z "$APK_PATH" ]]; then
    APK_PATH=$(find . -type f -path "*/build/outputs/apk/release/*.apk" 2>/dev/null | head -1)
fi

cp "$APK_PATH" "$SCRIPT_DIR/unsigned.apk"
