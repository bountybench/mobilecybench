#!/bin/bash

# ---
# APK Repackaging Script
#
# This script decompiles an APK, injects a non-exported "honeypot"
# activity, and then recompiles and signs it.
#
# Usage: ./repackage-apk.sh /path/to/your-app.apk
# ---

set -e

ANDROID_HOME="${HOME}/.android-sdk"
APKSIGNER="$ANDROID_HOME/build-tools/*/apksigner"
ZIPALIGN="$ANDROID_HOME/build-tools/*/zipalign"
# Fix path for Windows MinGW users
if [[ "$OSTYPE" == "msys" ]]; then
    {
        APKSIGNER="$ANDROID_HOME/build-tools/*/apksigner.bat"
        ZIPALIGN="$ANDROID_HOME/build-tools/*/zipalign.exe"
    }
fi
APKSIGNER=$(ls $APKSIGNER 2>/dev/null | head -1)
ZIPALIGN=$(ls $ZIPALIGN 2>/dev/null | head -1)

# Temporary directories and filenames
SOURCE_DIR="temp_app_source"
UNSIGNED_APK="unsigned-app.apk"
ALIGNED_APK="aligned-app.apk"

# Cleanup function to remove temporary files
cleanup() {
    if [ -d "$SOURCE_DIR" ]; then
        echo "Cleaning up temporary files..."
        rm -rf "$SOURCE_DIR"
    fi
    if [ -f "$UNSIGNED_APK" ]; then
        rm -f "$UNSIGNED_APK"
    fi
    if [ -f "$UNSIGNED_APK.signed" ]; then
        rm -f "$UNSIGNED_APK.signed"
    fi
    if [ -f "$UNSIGNED_APK.signed.idsig" ]; then
        rm -f "$UNSIGNED_APK.signed.idsig"
    fi
    if [ -f "$ALIGNED_APK" ]; then
        rm -f "$ALIGNED_APK"
    fi
}

# Set trap to cleanup on exit (including errors)
trap cleanup EXIT

# Path to the APK file
TARGET_APK="$1"

# Check if an APK file was provided
if [ -z "$TARGET_APK" ]; then
    echo "Usage: $0 /path/to/your-app.apk"
    exit 1
fi

# Validate APK file exists
if [ ! -f "$TARGET_APK" ]; then
    echo "Error: File '$TARGET_APK' does not exist."
    exit 1
fi

# Get script directory before changing directories
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

render_honeypot() {
    local format="$1"
    local package_name="$2"
    PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}" \
        python3 -m utils.honeypot_spec --format "$format" --package "$package_name"
}

# Get absolute path and extract filename components
TARGET_APK=$(realpath "$TARGET_APK")
APK_DIR=$(dirname "$TARGET_APK")
APK_BASENAME=$(basename "$TARGET_APK" .apk)
ORIGINAL_APK="${APK_BASENAME}-unmodified.apk"
FINAL_APK="${APK_BASENAME}.apk"

# Change to APK directory
cd "$APK_DIR"

# Check if original backup already exists
if [ -f "$ORIGINAL_APK" ]; then
    echo "Warning: Backup file '$ORIGINAL_APK' already exists."
    echo "This APK may have already been processed. Skipping."
    exit 0
fi

# Check if required tools are installed
command -v apktool >/dev/null 2>&1 || { echo >&2 "Error: 'apktool' is not installed. Aborting."; exit 1; }
command -v keytool >/dev/null 2>&1 || { echo >&2 "Error: 'keytool' is not installed (part of JDK). Aborting."; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo >&2 "Error: 'python3' is not installed. Aborting."; exit 1; }
[ -f "$APKSIGNER" ] || { echo >&2 "Error: 'apksigner' is not installed (part of Android SDK). Expected at: $APKSIGNER"; exit 1; }
[ -f "$ZIPALIGN" ] || { echo >&2 "Error: 'zipalign' is not installed (part of Android SDK). Expected at: $ZIPALIGN"; exit 1; }

# Keystore configuration (stored in script directory to be reused across APKs)
KEYSTORE_NAME="${SCRIPT_DIR}/benchmark.keystore"
KEYSTORE_PASS="password"
KEY_ALIAS="benchmark-key"

echo "--- Starting Repackaging Process for: $FINAL_APK ---"

echo "[1/9] Decompiling APK..."
if [ -d "$SOURCE_DIR" ]; then
    echo "Warning: '$SOURCE_DIR' directory already exists. Removing it."
    rm -rf "$SOURCE_DIR"
fi
apktool d "$FINAL_APK" -o "$SOURCE_DIR" -f > /dev/null

echo "[2/9] Detecting package name..."
PACKAGE_NAME=$(grep "package=" "$SOURCE_DIR/AndroidManifest.xml" | head -n 1 | sed -E 's/.*package="([^"]+)".*/\1/')
if [ -z "$PACKAGE_NAME" ]; then
    echo "Error: Could not detect package name."
    exit 1
fi
echo "Package detected: $PACKAGE_NAME"

# Check if honeypot already exists
ACTIVITY_NAME="$(render_honeypot activity-name "$PACKAGE_NAME")"
if grep -q "$ACTIVITY_NAME" "$SOURCE_DIR/AndroidManifest.xml"; then
    echo "Warning: Honeypot activity '$ACTIVITY_NAME' already exists in this APK."
    echo "This APK has already been processed. Skipping."
    exit 0
fi

# Convert package name to directory path
ACTIVITY_CLASS="$(render_honeypot activity-class "$PACKAGE_NAME")"
PACKAGE_ACTIVITY_DIR="$(render_honeypot activity-dir "$PACKAGE_NAME")"

# Detect smali directory (handle multidex APKs)
# Senior Review: Find the LAST dex index to ensure we don't exceed limits in classes.dex
LAST_DEX_INDEX=$(ls -1 "$SOURCE_DIR" | grep "smali_classes" | sed 's/smali_classes//' | sort -n | tail -1)
if [ -z "$LAST_DEX_INDEX" ]; then
    # Only smali/ exists
    SMALI_BASE="$SOURCE_DIR/smali"
else
    SMALI_BASE="$SOURCE_DIR/smali_classes$LAST_DEX_INDEX"
fi

if [ ! -d "$SMALI_BASE" ]; then
    echo "Error: Could not determine smali directory in decompiled APK."
    exit 1
fi

SMALI_PATH="$SMALI_BASE/$PACKAGE_ACTIVITY_DIR"

echo "[3/9] Injecting honeypot smali activity..."
mkdir -p "$SMALI_PATH"

# Write the minimal .smali activity file
render_honeypot smali "$PACKAGE_NAME" > "$SMALI_PATH/${ACTIVITY_CLASS}.smali"

echo "[4/9] Modifying AndroidManifest.xml..."
MANIFEST_FILE="$SOURCE_DIR/AndroidManifest.xml"

# Remove debuggable flag if present (to prevent debug-only exploits)
if grep -q 'android:debuggable="true"' "$MANIFEST_FILE"; then
    echo "Removing android:debuggable flag from manifest..."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' 's/android:debuggable="true"//g' "$MANIFEST_FILE"
    else
        sed -i 's/android:debuggable="true"//g' "$MANIFEST_FILE"
    fi
fi

# The <activity> tag to be injected
ACTIVITY_TAG="$(render_honeypot manifest-tag "$PACKAGE_NAME")"

# Use robust Python XML injector instead of sed
PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}" \
    python3 -m utils.discovery_honeypot "$MANIFEST_FILE" --package "$PACKAGE_NAME" --mode manifest

# Verify the modification was successful
if ! grep -q "$ACTIVITY_NAME" "$MANIFEST_FILE"; then
    echo "Error: Failed to inject activity into AndroidManifest.xml"
    exit 1
fi

echo "[5/9] Recompiling APK..."
apktool b "$SOURCE_DIR" -o "$UNSIGNED_APK" > /dev/null

echo "[6/9] Checking for signing key..."
if [ ! -f "$KEYSTORE_NAME" ]; then
    echo "No keystore found. Creating '$KEYSTORE_NAME'..."
    keytool -genkey -v -keystore "$KEYSTORE_NAME" \
            -alias "$KEY_ALIAS" -keyalg RSA -keysize 2048 \
            -validity 10000 -storepass "$KEYSTORE_PASS" -keypass "$KEYSTORE_PASS" \
            -dname "CN=Benchmark, OU=Test, O=Test, L=Test, S=Test, C=US"
else
    echo "Using existing keystore."
fi

echo "[7/9] Aligning APK..."
$ZIPALIGN -p -f 4 "$UNSIGNED_APK" "$ALIGNED_APK" > /dev/null

echo "[8/9] Signing the final APK..."
$APKSIGNER sign --ks "$KEYSTORE_NAME" --ks-pass "pass:$KEYSTORE_PASS" \
              --out "$UNSIGNED_APK.signed" "$ALIGNED_APK" > /dev/null

echo "[9/9] Verifying APK signature..."
$APKSIGNER verify "$UNSIGNED_APK.signed" > /dev/null || { echo "Error: APK signature verification failed"; exit 1; }

echo "Renaming original APK to: $ORIGINAL_APK"
mv "$FINAL_APK" "$ORIGINAL_APK"

# Move signed APK to original name
echo "Saving repackaged APK as: $FINAL_APK"
mv "$UNSIGNED_APK.signed" "$FINAL_APK"

echo ""
echo "--- ✅ Success! ---"
echo "Original APK backed up to: $APK_DIR/$ORIGINAL_APK"
echo "Repackaged APK saved as: $APK_DIR/$FINAL_APK"
echo "Honeypot Activity: $ACTIVITY_NAME"
