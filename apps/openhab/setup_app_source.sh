#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0"
  echo "Builds the OpenHAB mobile module and outputs openhab.apk"
}

MODULE_NAME="mobile"

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
CODEBASE_DIR="$ROOT_DIR/codebase"
MODULE_DIR="$CODEBASE_DIR/$MODULE_NAME"

echo "Building module: $MODULE_NAME -> output name: openhab"
echo "ROOT_DIR: $ROOT_DIR"
echo "CODEBASE_DIR: $CODEBASE_DIR"

if [ ! -f "$CODEBASE_DIR/gradlew" ]; then
  echo "gradlew not found in codebase directory ($CODEBASE_DIR). Make sure the Android project exists in the codebase directory." >&2
  exit 2
fi

if [ ! -d "$MODULE_DIR" ]; then
  echo "Module directory '$MODULE_DIR' not found. The mobile module is required for OpenHAB." >&2
  exit 3
fi

find_tool() {
  # $1 = tool name
  if command -v "$1" >/dev/null 2>&1; then
    command -v "$1"
    return 0
  fi

  local sdkroot="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-}}"
  if [ -n "$sdkroot" ] && [ -d "$sdkroot/build-tools" ]; then
    # pick newest build-tools version available
    local bt
    bt=$(ls -1 "$sdkroot/build-tools" | sort -V | tail -n1 || true)
    if [ -n "$bt" ] && [ -x "$sdkroot/build-tools/$bt/$1" ]; then
      echo "$sdkroot/build-tools/$bt/$1"
      return 0
    fi
  fi

  return 1
}

APKSIGNER="$(find_tool apksigner || true)"
ZIPALIGN="$(find_tool zipalign || true)"

if [ -z "$APKSIGNER" ]; then
  if command -v apksigner >/dev/null 2>&1; then
    APKSIGNER=$(command -v apksigner)
  else
    echo "apksigner not found. Please ensure Android build-tools are installed and ANDROID_SDK_ROOT/ANDROID_HOME is set or apksigner is on PATH." >&2
    exit 4
  fi
fi

if [ -z "$ZIPALIGN" ]; then
  if command -v zipalign >/dev/null 2>&1; then
    ZIPALIGN=$(command -v zipalign)
  else
    echo "zipalign not found. Please ensure Android build-tools are installed and ANDROID_SDK_ROOT/ANDROID_HOME is set or zipalign is on PATH." >&2
    exit 5
  fi
fi

echo "Using apksigner: $APKSIGNER"
echo "Using zipalign: $ZIPALIGN"

# Configure Gradle JVM memory settings
GRADLE_PROPERTIES="$CODEBASE_DIR/gradle.properties"
echo "Configuring Gradle JVM memory settings in $GRADLE_PROPERTIES"

if [ -f "$GRADLE_PROPERTIES" ]; then
  # Backup original gradle.properties
  cp "$GRADLE_PROPERTIES" "$GRADLE_PROPERTIES.backup"

  # Remove any existing org.gradle.jvmargs line
  sed -i.tmp '/^org\.gradle\.jvmargs=/d' "$GRADLE_PROPERTIES"
  rm -f "$GRADLE_PROPERTIES.tmp"

  # Add the new JVM args
  echo "org.gradle.jvmargs=-Xmx4g" >> "$GRADLE_PROPERTIES"
else
  # Create gradle.properties if it doesn't exist
  echo "org.gradle.jvmargs=-Xmx4g" > "$GRADLE_PROPERTIES"
fi

echo "Set org.gradle.jvmargs=-Xmx4g in gradle.properties"

# Run Gradle assembleRelease
echo "Running Gradle assembleRelease for module :$MODULE_NAME"
cd "$CODEBASE_DIR"
./gradlew ":$MODULE_NAME:clean" ":$MODULE_NAME:assembleRelease" --no-daemon -x lint
cd "$ROOT_DIR"

# Locate release APK (prefer already aligned release APKs, else unsigned)
APK_CANDIDATE=""
while IFS= read -r -d $'\0' f; do
  APK_CANDIDATE="$f"
  break
done < <(find "$MODULE_DIR/build/outputs/apk" -type f \( -iname "*release.apk" -o -iname "*release-unsigned.apk" \) -print0 | sort -z)

if [ -z "$APK_CANDIDATE" ]; then
  echo "Could not find any release APK under $MODULE_DIR/build/outputs/apk" >&2
  exit 6
fi

echo "Found APK candidate: $APK_CANDIDATE"

TMP_DIR=$(mktemp -d)
SIGNED_APK="$TMP_DIR/openhab.apk"

# Prepare keystore
KEYSTORE_FILE=""
if [ -n "${ANDROID_KEYSTORE_BASE64:-}" ]; then
  echo "Decoding ANDROID_KEYSTORE_BASE64 to temporary keystore"
  KEYSTORE_FILE="$TMP_DIR/keystore.jks"
  echo "$ANDROID_KEYSTORE_BASE64" | base64 --decode > "$KEYSTORE_FILE"
elif [ -n "${ANDROID_KEYSTORE_PATH:-}" ]; then
  KEYSTORE_FILE="$ANDROID_KEYSTORE_PATH"
fi

if [ -z "$KEYSTORE_FILE" ]; then
  echo "No keystore provided. Generating an ephemeral keystore for CI signing."
  KEYSTORE_FILE="$TMP_DIR/ci_keystore.jks"
  KEYSTORE_PASSWORD="${KEYSTORE_PASSWORD:-android}"
  KEY_ALIAS="${KEY_ALIAS:-ci}" 
  KEY_PASSWORD="${KEY_PASSWORD:-$KEYSTORE_PASSWORD}"
  keytool -genkeypair -v -keystore "$KEYSTORE_FILE" -storepass "$KEYSTORE_PASSWORD" -keypass "$KEY_PASSWORD" -alias "$KEY_ALIAS" -dname "CN=CI, OU=CI, O=CI, L=CI, S=CI, C=US" -keyalg RSA -keysize 2048 -validity 10000 >/dev/null 2>&1
else
  # require passwords/alias
  KEYSTORE_PASSWORD="${KEYSTORE_PASSWORD:-}"
  KEY_ALIAS="${KEY_ALIAS:-}"
  KEY_PASSWORD="${KEY_PASSWORD:-${KEYSTORE_PASSWORD:-}}"
  if [ -z "$KEYSTORE_PASSWORD" ] || [ -z "$KEY_ALIAS" ]; then
    echo "When providing a keystore, KEYSTORE_PASSWORD and KEY_ALIAS environment variables must be set." >&2
    exit 7
  fi
fi

echo "Signing APK..."

# If the APK is unsigned (contains "unsigned" or not zipaligned), we will zipalign then sign.
UNSIGNED=0
if [[ "$APK_CANDIDATE" == *unsigned.apk ]] || [[ "$APK_CANDIDATE" != *.apk ]]; then
  UNSIGNED=1
fi

# Always produce a zipaligned, signed APK at $SIGNED_APK
ALIGNED="$TMP_DIR/aligned.apk"

echo "Zipaligning APK to $ALIGNED"
"$ZIPALIGN" -v -p 4 "$APK_CANDIDATE" "$ALIGNED"

echo "Running apksigner"
"$APKSIGNER" sign --ks "$KEYSTORE_FILE" --ks-pass pass:"$KEYSTORE_PASSWORD" --key-pass pass:"$KEY_PASSWORD" --ks-key-alias "$KEY_ALIAS" --out "$SIGNED_APK" "$ALIGNED"

echo "Verifying signed APK"
"$APKSIGNER" verify "$SIGNED_APK"

DEST_DIR="$ROOT_DIR/apk"
mkdir -p "$DEST_DIR"
DEST_PATH="$DEST_DIR/openhab.apk"

cp "$SIGNED_APK" "$DEST_PATH"

echo "Signed APK copied to: $DEST_PATH"

echo "Cleaning temporary files"
rm -rf "$TMP_DIR"

# Restore original gradle.properties if backup exists
if [ -f "$GRADLE_PROPERTIES.backup" ]; then
  echo "Restoring original gradle.properties"
  mv "$GRADLE_PROPERTIES.backup" "$GRADLE_PROPERTIES"
fi

echo "Done."
