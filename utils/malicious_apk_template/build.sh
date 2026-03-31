#!/usr/bin/env bash
set -euo pipefail

: "${ANDROID_HOME:?Set ANDROID_HOME}"

# Use the highest available build-tools version
BUILD_TOOLS_DIR="$ANDROID_HOME/build-tools"
BUILD_TOOLS_VERSION=$(ls "$BUILD_TOOLS_DIR" | sort -V | tail -1)
BUILD_TOOLS="$BUILD_TOOLS_DIR/$BUILD_TOOLS_VERSION"

PLATFORM_DIR="$ANDROID_HOME/platforms"
PLATFORM_VERSION=$(ls "$PLATFORM_DIR" | sort -V | tail -1)
ANDROID_JAR="$PLATFORM_DIR/$PLATFORM_VERSION/android.jar"

AAPT="$BUILD_TOOLS/aapt"
ZIPALIGN="$BUILD_TOOLS/zipalign"
APKSIGNER="$BUILD_TOOLS/apksigner"
D8="$BUILD_TOOLS/d8"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$SCRIPT_DIR/src"
BUILD_DIR="$SCRIPT_DIR/build"
CLASSES_DIR="$BUILD_DIR/classes"
DEX_DIR="$BUILD_DIR/dex"
DIST_DIR="$SCRIPT_DIR/dist"
APK_UNALIGNED="$DIST_DIR/app-unaligned.apk"
APK_ALIGNED="$DIST_DIR/app-aligned.apk"
APK_SIGNED="$DIST_DIR/com.mobilecybench.apk"

rm -rf "$BUILD_DIR" "$DIST_DIR"
mkdir -p "$CLASSES_DIR" "$DEX_DIR" "$DIST_DIR"

# Compile all Java sources
echo "Compiling sources..."
JAVA_FILES=$(find "$SRC_DIR" -name '*.java')
if [ -z "$JAVA_FILES" ]; then
    echo "ERROR: No .java files found in $SRC_DIR" >&2
    exit 1
fi
javac -source 1.8 -target 1.8 \
    -bootclasspath "$ANDROID_JAR" \
    -classpath "$ANDROID_JAR" \
    -d "$CLASSES_DIR" \
    $JAVA_FILES

# Create DEX
echo "Creating dex..."
CLASS_FILES=$(find "$CLASSES_DIR" -name '*.class')
"$D8" --min-api 21 \
    --lib "$ANDROID_JAR" \
    --output "$DEX_DIR" \
    $CLASS_FILES

# Package APK
echo "Packaging APK..."
"$AAPT" package -f \
    -M "$SCRIPT_DIR/AndroidManifest.xml" \
    -I "$ANDROID_JAR" \
    -F "$APK_UNALIGNED"

cd "$DEX_DIR" && zip -q "$APK_UNALIGNED" classes.dex && cd - >/dev/null

"$ZIPALIGN" -f 4 "$APK_UNALIGNED" "$APK_ALIGNED"

# Sign APK
KEYSTORE="$SCRIPT_DIR/debug.keystore"
ALIAS="androiddebugkey"
STOREPASS="android"
KEYPASS="android"

if [ ! -f "$KEYSTORE" ]; then
    keytool -genkeypair -v -keystore "$KEYSTORE" -storepass "$STOREPASS" \
        -alias "$ALIAS" -keypass "$KEYPASS" -keyalg RSA -keysize 2048 -validity 3650 \
        -dname "CN=Android Debug,O=Android,C=US"
fi

"$APKSIGNER" sign --ks "$KEYSTORE" --ks-pass pass:"$STOREPASS" \
    --key-pass pass:"$KEYPASS" --ks-key-alias "$ALIAS" \
    --out "$APK_SIGNED" "$APK_ALIGNED"

# Clean up intermediate artifacts
rm -rf "$BUILD_DIR"
rm -f "$APK_UNALIGNED" "$APK_ALIGNED" "$APK_SIGNED.idsig"

echo "Built $APK_SIGNED"
