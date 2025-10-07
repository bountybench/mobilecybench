
#!/bin/bash
set -e

check_prerequisites() {
    if ! command -v java >/dev/null 2>&1; then
        echo "Java not found. Please install Java 17."
        exit 1
    fi

    # More robust check for the Android SDK path.
    if [ -n "$ANDROID_HOME" ] && [ -d "$ANDROID_HOME" ]; then
        echo "Found AH: $ANDROID_HOME"
    elif [ -d "${HOME}/.android-sdk" ]; then
      # Fallback to the default path if ANDROID_HOME isn't set.
      ANDROID_HOME="${HOME}/.android-sdk"
    fi
    if [[ ! -d "$ANDROID_HOME" ]]; then
        echo "Android home not found"
        exit 1
    fi

}

check_prerequisites
cd codebase 
# Continue with Gradle build
mkdir -p ../apk
./gradlew  assembleRelease && cp app/build/outputs/apk/libre/release/app-libre-release-unsigned.apk ../apk/keepassdx.apk

cd ..
APKSIGNER=$(ls -d $ANDROID_HOME/build-tools/*/apksigner | sort -V | tail -n 1)

"$APKSIGNER" sign --ks keepass.keystore --ks-pass pass:keepass apk/keepassdx.apk

"$APKSIGNER" verify apk/keepassdx.apk


