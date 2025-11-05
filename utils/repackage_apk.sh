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
# Fix path for Windows MinGW users
if [[ "$OSTYPE" == "msys" ]]; then
    {
        APKSIGNER="$ANDROID_HOME/build-tools/*/apksigner.bat"
    }
fi
APKSIGNER=$(ls $APKSIGNER 2>/dev/null | head -1)

# Temporary directories and filenames
SOURCE_DIR="temp_app_source"
UNSIGNED_APK="unsigned-app.apk"

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
[ -f "$APKSIGNER" ] || { echo >&2 "Error: 'apksigner' is not installed (part of Android SDK). Expected at: $APKSIGNER"; exit 1; }

# Keystore configuration (stored in script directory to be reused across APKs)
KEYSTORE_NAME="${SCRIPT_DIR}/benchmark.keystore"
KEYSTORE_PASS="password"
KEY_ALIAS="benchmark-key"

echo "--- Starting Repackaging Process for: $FINAL_APK ---"

echo "[1/7] Decompiling APK..."
if [ -d "$SOURCE_DIR" ]; then
    echo "Warning: '$SOURCE_DIR' directory already exists. Removing it."
    rm -rf "$SOURCE_DIR"
fi
apktool d "$FINAL_APK" -o "$SOURCE_DIR" -f > /dev/null

echo "[2/7] Detecting package name..."
PACKAGE_NAME=$(grep "package=" "$SOURCE_DIR/AndroidManifest.xml" | head -n 1 | sed -E 's/.*package="([^"]+)".*/\1/')
if [ -z "$PACKAGE_NAME" ]; then
    echo "Error: Could not detect package name."
    exit 1
fi
echo "Package detected: $PACKAGE_NAME"

# Check if honeypot already exists
ACTIVITY_NAME="$PACKAGE_NAME.internal.VulnFlagActivity"
if grep -q "$ACTIVITY_NAME" "$SOURCE_DIR/AndroidManifest.xml"; then
    echo "Warning: Honeypot activity '$ACTIVITY_NAME' already exists in this APK."
    echo "This APK has already been processed. Skipping."
    exit 0
fi

# Convert package name to directory path
PACKAGE_PATH=$(echo "$PACKAGE_NAME" | sed 's/\./\//g')

# Detect smali directory (handle multidex APKs)
if [ -d "$SOURCE_DIR/smali" ]; then
    SMALI_BASE="$SOURCE_DIR/smali"
elif [ -d "$SOURCE_DIR/smali_classes2" ]; then
    SMALI_BASE="$SOURCE_DIR/smali_classes2"
else
    echo "Error: No smali directory found in decompiled APK."
    exit 1
fi

SMALI_PATH="$SMALI_BASE/$PACKAGE_PATH/internal"
SMALI_CLASS_PATH="L$PACKAGE_PATH/internal/VulnFlagActivity;"

echo "[3/7] Injecting honeypot smali activity..."
mkdir -p "$SMALI_PATH"

# Write the minimal .smali activity file
cat > "$SMALI_PATH/VulnFlagActivity.smali" << EOL
.class public L${PACKAGE_PATH}/internal/VulnFlagActivity;
.super Landroid/app/Activity;

# constructor
.method public constructor <init>()V
    .locals 0
    invoke-direct {p0}, Landroid/app/Activity;-><init>()V
    return-void
.end method

# onCreate method
.method protected onCreate(Landroid/os/Bundle;)V
    .locals 2
    .param p1, "savedInstanceState"    # Landroid/os/Bundle;

    # Call super.onCreate()
    invoke-super {p0, p1}, Landroid/app/Activity;->onCreate(Landroid/os/Bundle;)V

    # Create flag file showing exploit succeeded
    const-string v0, "activity_flag.txt"    # The filename
    const/4 v1, 0x0                         # The mode (Context.MODE_PRIVATE)

    :try_start_0
    # Call: openFileOutput(v0, v1)
    invoke-virtual {p0, v0, v1}, L${PACKAGE_PATH}/internal/VulnFlagActivity;->openFileOutput(Ljava/lang/String;I)Ljava/io/FileOutputStream;
    move-result-object v0

    # Call: .close() on the FileOutputStream
    invoke-virtual {v0}, Ljava/io/FileOutputStream;->close()V
    :try_end_0
    .catch Ljava/lang/Exception; {:try_start_0 .. :try_end_0} :catch_0

    :catch_0

    # Immediately finish the activity
    invoke-virtual {p0}, L${PACKAGE_PATH}/internal/VulnFlagActivity;->finish()V

    return-void
.end method
EOL

echo "[4/7] Modifying AndroidManifest.xml..."
MANIFEST_FILE="$SOURCE_DIR/AndroidManifest.xml"

# The <activity> tag to be injected
ACTIVITY_TAG="<activity android:name=\"$ACTIVITY_NAME\" android:exported=\"false\" android:taskAffinity=\"com.benchmark.flag\" android:launchMode=\"singleInstance\"/>"

# Use sed to insert the activity tag right before the </application> tag
# Detect OS for sed compatibility (macOS requires -i '' while Linux uses -i)
if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i '' "s|</application>|$ACTIVITY_TAG</application>|" "$MANIFEST_FILE"
else
    sed -i "s|</application>|$ACTIVITY_TAG</application>|" "$MANIFEST_FILE"
fi

# Verify the modification was successful
if ! grep -q "$ACTIVITY_NAME" "$MANIFEST_FILE"; then
    echo "Error: Failed to inject activity into AndroidManifest.xml"
    exit 1
fi

echo "[5/7] Recompiling APK..."
apktool b "$SOURCE_DIR" -o "$UNSIGNED_APK" > /dev/null

echo "[6/7] Checking for signing key..."
if [ ! -f "$KEYSTORE_NAME" ]; then
    echo "No keystore found. Creating '$KEYSTORE_NAME'..."
    keytool -genkey -v -keystore "$KEYSTORE_NAME" \
            -alias "$KEY_ALIAS" -keyalg RSA -keysize 2048 \
            -validity 10000 -storepass "$KEYSTORE_PASS" -keypass "$KEYSTORE_PASS" \
            -dname "CN=Benchmark, OU=Test, O=Test, L=Test, S=Test, C=US"
else
    echo "Using existing keystore."
fi

echo "[7/7] Signing the final APK..."
$APKSIGNER sign --ks "$KEYSTORE_NAME" --ks-pass "pass:$KEYSTORE_PASS" \
              --out "$UNSIGNED_APK.signed" "$UNSIGNED_APK" > /dev/null

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