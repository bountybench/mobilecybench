set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CODEBASE_DIR="$SCRIPT_DIR/codebase"
APK_UNSIGNED="$CODEBASE_DIR/app/build/outputs/apk/release/app-release-unsigned.apk"
APK_OUT="$SCRIPT_DIR/apk/wallabag-release.apk"

echo "[Wallabag] Building Wallabag Android app from source..."

if [ ! -d "$CODEBASE_DIR" ]; then
    echo "Error: codebase directory not found."
    exit 1
fi

cd "$CODEBASE_DIR"

export ANDROID_HOME="${ANDROID_HOME:-$HOME/.android-sdk}"
export PATH="$ANDROID_HOME/platform-tools:$PATH"

./gradlew clean
./gradlew assembleRelease

KEYSTORE_FILE="$HOME/.android/debug.keystore"
APKSIGNER="$ANDROID_HOME/build-tools/$(ls -v "$ANDROID_HOME/build-tools" | tail -n 1)/apksigner"

if [ ! -f "$KEYSTORE_FILE" ]; then
    keytool -genkey -v -keystore "$KEYSTORE_FILE" \
        -alias androiddebugkey -keyalg RSA -keysize 2048 \
        -validity 10000 -storepass android -keypass android \
        -dname "CN=Android Debug, O=Android, C=US"
fi

"$APKSIGNER" sign \
    --ks "$KEYSTORE_FILE" \
    --ks-key-alias androiddebugkey \
    --ks-pass pass:android \
    --key-pass pass:android \
    "$APK_UNSIGNED"

cp "$APK_UNSIGNED" "$APK_OUT"
echo "[Wallabag] ✅ Release APK built and copied to $APK_OUT"
