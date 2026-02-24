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
GRADLE_JVMARGS="-Dfile.encoding=UTF-8 -XX:+UseG1GC -XX:SoftRefLRUPolicyMSPerMB=1 -XX:ReservedCodeCacheSize=256m -XX:+HeapDumpOnOutOfMemoryError -Xmx${GRADLE_XMX} -Xss8m"

# Patch gradle.properties to reduce memory limits for CI (prevent swapping)
GRADLE_PROPERTIES="$SCRIPT_DIR/codebase/gradle.properties"
if [[ -f "$GRADLE_PROPERTIES" ]] && ! grep -q 'tbFastReleaseMemoryOptimized' "$GRADLE_PROPERTIES"; then
  echo "Applying memory limit patches to gradle.properties..."
  # Reduce Kotlin daemon and Gradle worker memory from 8g to 2g to fit in CI runner (prevent swapping)
  perl -i -pe 's/Xmx8g/Xmx2048m/g' "$GRADLE_PROPERTIES"
  perl -i -pe 's/Xms8g/Xms512m/g' "$GRADLE_PROPERTIES"
  echo "# tbFastReleaseMemoryOptimized" >> "$GRADLE_PROPERTIES"
fi

# Patch settings.gradle.kts to prune unnecessary modules (e.g. K-9 and CLI tools)
SETTINGS_GRADLE="$SCRIPT_DIR/codebase/settings.gradle.kts"
if [[ -f "$SETTINGS_GRADLE" ]] && ! grep -q 'tbFastReleaseSettingsPruned' "$SETTINGS_GRADLE"; then
  echo "Pruning settings.gradle.kts to remove non-essential modules..."
  perl -i -pe 's/":app-k9mail",//g' "$SETTINGS_GRADLE"
  perl -i -pe 's/":app-ui-catalog",//g' "$SETTINGS_GRADLE"
  perl -i -pe 's/":cli:.*",//g' "$SETTINGS_GRADLE"
  perl -i -pe 's/":quality:konsist",//g' "$SETTINGS_GRADLE"
  echo "// tbFastReleaseSettingsPruned" >> "$SETTINGS_GRADLE"
fi

# Patch root build.gradle.kts to disable quality plugins globally
ROOT_GRADLE="$SCRIPT_DIR/codebase/build.gradle.kts"
if [[ -f "$ROOT_GRADLE" ]] && ! grep -q 'tbFastReleaseGlobalQualityDisabled' "$ROOT_GRADLE"; then
  echo "Disabling quality tasks globally in root build.gradle.kts..."
  echo -e "\nsubprojects {\n    tasks.configureEach {\n        val taskName = name.lowercase()\n        if (taskName.contains(\"detekt\") || taskName.contains(\"spotless\") || taskName.contains(\"lint\") || taskName.contains(\"dependencyguard\")) {\n            enabled = false\n        }\n    }\n}\n// tbFastReleaseGlobalQualityDisabled" >> "$ROOT_GRADLE"
fi

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

# Additional fast-mode config trimming: remove non-essential quality/plugin wiring.
if [[ "$TB_FAST_RELEASE" == "true" ]] && [[ -f "$APP_GRADLE" ]] && ! grep -q 'tbFastReleasePluginsTrimmed' "$APP_GRADLE"; then
  echo "Applying fast-release plugin/config trimming..."
  perl -0777 -i -pe 's/\n\s*alias\(libs\.plugins\.dependency\.guard\)\n/\n/s' "$APP_GRADLE"
  perl -0777 -i -pe 's/\n\s*id\(\"thunderbird\.quality\.badging\"\)\n/\n/s' "$APP_GRADLE"
  perl -0777 -i -pe 's/\ndependencyGuard \{[\s\S]*?\n\}\n/\n\/\/ tbFastReleasePluginsTrimmed\n/s' "$APP_GRADLE"
fi

# Add abiFilters to app-thunderbird/build.gradle.kts
if [[ -f "$APP_GRADLE" ]] && ! grep -q 'tbFastReleaseAbiFiltered' "$APP_GRADLE"; then
  echo "Adding x86_64 ABI filter..."
  perl -0777 -i -pe 's/(defaultConfig \{)/$1\n        ndk {\n            abiFilters += "x86_64"\n        }/s' "$APP_GRADLE"
  echo "// tbFastReleaseAbiFiltered" >> "$APP_GRADLE"
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
