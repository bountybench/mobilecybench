#!/usr/bin/env bash
set -euo pipefail

: "${ANDROID_HOME:?Set ANDROID_HOME}"

# Use API 34 for compile (fine even if device is API 28)
PLATFORM="$ANDROID_HOME/platforms/android-34"
ANDROID_JAR="$PLATFORM/android.jar"

# Pick a stable build-tools (34.0.0 works)
BUILD_TOOLS="$ANDROID_HOME/build-tools/34.0.0"
AAPT="$BUILD_TOOLS/aapt"
ZIPALIGN="$BUILD_TOOLS/zipalign"
APKSIGNER="$BUILD_TOOLS/apksigner"
D8="$BUILD_TOOLS/d8"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="$SCRIPT_DIR/dist"
BUILD_DIR="$SCRIPT_DIR/build"
CLASSES_DIR="$BUILD_DIR/classes"
DEX_DIR="$BUILD_DIR/dex"
APK_UNALIGNED="$OUT_DIR/perm_only-unaligned.apk"
APK_ALIGNED="$OUT_DIR/perm_only-aligned.apk"
APK_SIGNED="$OUT_DIR/malicious-perm-only.apk"

rm -rf "$BUILD_DIR" "$OUT_DIR"
mkdir -p "$CLASSES_DIR" "$DEX_DIR" "$OUT_DIR"

echo "Compiling Java sources..."
javac -source 1.8 -target 1.8 \
  -bootclasspath "$ANDROID_JAR" \
  -classpath "$ANDROID_JAR" \
  -d "$CLASSES_DIR" \
  "$SCRIPT_DIR/src/com/test/malicious/MainActivity.java"

echo "Creating dex..."
"$D8" --min-api 21 \
  --lib "$ANDROID_JAR" \
  --output "$DEX_DIR" \
  "$CLASSES_DIR/com/test/malicious/MainActivity.class"

echo "Packaging APK..."
# Create APK with manifest only first
"$AAPT" package -f \
  -M "$SCRIPT_DIR/AndroidManifest.xml" \
  -I "$ANDROID_JAR" \
  -F "$APK_UNALIGNED"

echo "Adding classes.dex to APK..."
# Use zip command to add classes.dex with the correct name
cd "$DEX_DIR" && zip -q "$APK_UNALIGNED" classes.dex && cd - >/dev/null

echo "Aligning APK..."
"$ZIPALIGN" -f 4 "$APK_UNALIGNED" "$APK_ALIGNED"

echo "Signing APK..."
KEYSTORE="$SCRIPT_DIR/debug.keystore"
ALIAS=${ALIAS:-androiddebugkey}
STOREPASS=${STOREPASS:-android}
KEYPASS=${KEYPASS:-android}

if [ ! -f "$KEYSTORE" ]; then
  keytool -genkeypair -v -keystore "$KEYSTORE" -storepass "$STOREPASS" \
    -alias "$ALIAS" -keypass "$KEYPASS" -keyalg RSA -keysize 2048 -validity 3650 \
    -dname "CN=Android Debug,O=Android,C=US"
fi

"$APKSIGNER" sign --ks "$KEYSTORE" --ks-pass pass:"$STOREPASS" \
  --key-pass pass:"$KEYPASS" --ks-key-alias "$ALIAS" \
  --out "$APK_SIGNED" "$APK_ALIGNED"

cp "$APK_SIGNED" "$SCRIPT_DIR/../malicious-perm-only.apk"
echo "Built $APK_SIGNED and copied to ../malicious-perm-only.apk"
