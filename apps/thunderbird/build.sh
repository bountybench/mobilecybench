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

# Build only one variant to avoid building both foss and full (faster + deterministic).
./gradlew :app-thunderbird:assembleFossRelease \
  --no-daemon \
  --max-workers=2 \
  --console=plain \
  --build-cache \
  -Dorg.gradle.caching=true \
  -Dorg.gradle.parallel=true \
  -Dorg.gradle.jvmargs="${GRADLE_JVMARGS}" \
  -x test -x lint

APK="$(find app-thunderbird/build/outputs/apk -type f -name "*.apk" \
  | grep -E -i 'foss.*release|release.*foss|/foss/release/' \
  | head -n 1 || true)"
if [[ -z "$APK" ]]; then
  APK="$(find app-thunderbird/build/outputs/apk -type f -name "*release*.apk" | head -n 1 || true)"
fi
if [[ -z "$APK" ]]; then
  echo "ERROR: Release APK not found"
  exit 1
fi

cp "$APK" "$SCRIPT_DIR/unsigned.apk"
