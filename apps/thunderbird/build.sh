#!/bin/bash
set -euo pipefail

: "${KEYSTORE_PATH:?KEYSTORE_PATH is required}"
: "${KEYSTORE_PASSWORD:?KEYSTORE_PASSWORD is required}"
: "${KEYSTORE_ALIAS:?KEYSTORE_ALIAS is required}"
: "${KEYSTORE_ALIAS_PASSWORD:?KEYSTORE_ALIAS_PASSWORD is required}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

# Write signing config using unified keystore env vars from build_apk.sh
SIGNING_DIR="$SCRIPT_DIR/codebase/.signing"
mkdir -p "$SIGNING_DIR"

cat > "$SIGNING_DIR/tb.release.upload.properties" <<EOF
# Auto-generated for benchmark build
# Uses unified keystore from build_apk.sh

tb.release.storeFile=$KEYSTORE_PATH
tb.release.storePassword=$KEYSTORE_PASSWORD
tb.release.keyAlias=$KEYSTORE_ALIAS
tb.release.keyPassword=$KEYSTORE_ALIAS_PASSWORD
EOF

# Thunderbird's repo defaults (gradle.properties) set very large heaps (e.g. -Xmx8g -Xms8g), override with a smaller heap but keep useful defaults.
GRADLE_XMX="${GRADLE_XMX:-4096m}"
GRADLE_JVMARGS="-Dfile.encoding=UTF-8 -XX:+UseG1GC -XX:ReservedCodeCacheSize=256m -XX:+HeapDumpOnOutOfMemoryError -Xmx${GRADLE_XMX} -Xss8m"

# Release-only default (debug APKs are not acceptable for this app flow).
TB_BUILD_VARIANT="${TB_BUILD_VARIANT:-FossRelease}"
GRADLE_TASK=":app-thunderbird:assemble${TB_BUILD_VARIANT}"
TB_FAST_RELEASE="${TB_FAST_RELEASE:-true}"

build_log="$(mktemp /tmp/thunderbird-build.XXXXXX.log)"
trap 'rm -f "$build_log"' EXIT

if [[ "$TB_FAST_RELEASE" == "true" ]]; then
  echo "TB_FAST_RELEASE enabled (release minify/shrink disabled via Gradle property)."
else
  echo "TB_FAST_RELEASE disabled (full release optimization enabled)."
fi

# Ensure codebase supports -Ptb.fastRelease even after metadata commit checkout resets.
APP_GRADLE="$SCRIPT_DIR/codebase/app-thunderbird/build.gradle.kts"
if [[ -f "$APP_GRADLE" ]] && ! grep -q 'tb\.fastRelease' "$APP_GRADLE"; then
  echo "Patching app-thunderbird/build.gradle.kts to support tb.fastRelease..."
  perl -0777 -i -pe 's/(if \(testCoverageEnabled\) \{\n\s*apply\(plugin = "jacoco"\)\n\}\n)/$1val fastReleaseBuild = providers.gradleProperty("tb.fastRelease").orElse("false").get().toBoolean()\n\n/s' "$APP_GRADLE"
  perl -0777 -i -pe 's/(release\s*\{[^{}]*?isMinifyEnabled\s*=\s*)true/$1!fastReleaseBuild/s' "$APP_GRADLE"
  perl -0777 -i -pe 's/(release\s*\{[^{}]*?isShrinkResources\s*=\s*)true/$1!fastReleaseBuild/s' "$APP_GRADLE"
fi

# Extra CI speed-up: reduce locale packaging scope in fast mode.
if [[ "$TB_FAST_RELEASE" == "true" ]] && [[ -f "$APP_GRADLE" ]] && ! grep -q 'tbFastReleaseLocaleOptimized' "$APP_GRADLE"; then
  echo "Applying fast-release locale optimization..."
  perl -0777 -i -pe 's/localeFilters \+= listOf\([\s\S]*?\)/localeFilters += listOf("en") \/\/ tbFastReleaseLocaleOptimized/s' "$APP_GRADLE"
fi

# Largest speed lever: disable all variants except fossRelease in fast mode.
if [[ "$TB_FAST_RELEASE" == "true" ]] && [[ -f "$APP_GRADLE" ]] && ! grep -q 'tbFastReleaseVariantPruned' "$APP_GRADLE"; then
  echo "Applying fast-release variant pruning (keep only fossRelease)..."
  perl -0777 -i -pe 's/androidComponents \{\n/androidComponents {\n    beforeVariants { variantBuilder ->\n        if (fastReleaseBuild) {\n            val buildType = variantBuilder.buildType ?: \"\"\n            val flavors = variantBuilder.productFlavors.associate { it.first to it.second }\n            val appFlavor = flavors[\"app\"] ?: \"\"\n            val keep = buildType == \"release\" && appFlavor == \"foss\"\n            variantBuilder.enable = keep \/\/ tbFastReleaseVariantPruned\n        }\n    }\n/s' "$APP_GRADLE"
fi

# Build only one variant to avoid building both foss and full (faster + deterministic).
set +e
start_ts="$(date +%s)"
./gradlew "${GRADLE_TASK}" \
  --no-daemon \
  --max-workers=2 \
  --console=plain \
  --warning-mode=none \
  --build-cache \
  "-Ptb.fastRelease=${TB_FAST_RELEASE}" \
  -Dorg.gradle.caching=true \
  -Dorg.gradle.configuration-cache=true \
  -Dorg.gradle.configuration-cache.parallel=true \
  -Dorg.gradle.parallel=true \
  -Dorg.gradle.jvmargs="${GRADLE_JVMARGS}" \
  -x test -x lint >"$build_log" 2>&1 &
gradle_pid=$!

# Keep CI alive while Gradle output is redirected.
while kill -0 "$gradle_pid" 2>/dev/null; do
  sleep 60
  now_ts="$(date +%s)"
  elapsed="$((now_ts - start_ts))"
  echo "Thunderbird Gradle build in progress (${elapsed}s elapsed)..."
done

wait "$gradle_pid"
gradle_status=$?
set -e

if [[ $gradle_status -ne 0 ]]; then
  echo "Gradle build failed for ${GRADLE_TASK}. Last 200 log lines:"
  tail -n 200 "$build_log"
  exit $gradle_status
fi

APK="$(find app-thunderbird/build/outputs/apk -type f -name "*.apk" \
  | grep -E -i "foss.*${TB_BUILD_VARIANT#Foss}|${TB_BUILD_VARIANT#Foss}.*foss|/foss/${TB_BUILD_VARIANT#Foss,,}/" \
  | head -n 1 || true)"
if [[ -z "$APK" ]]; then
  # Fallbacks by build type
  if [[ "${TB_BUILD_VARIANT}" == *Debug ]]; then
    APK="$(find app-thunderbird/build/outputs/apk -type f -name "*debug*.apk" | head -n 1 || true)"
  else
    APK="$(find app-thunderbird/build/outputs/apk -type f -name "*release*.apk" | head -n 1 || true)"
  fi
fi
if [[ -z "$APK" ]]; then
  echo "ERROR: Release APK not found"
  exit 1
fi

cp "$APK" "$SCRIPT_DIR/unsigned.apk"
