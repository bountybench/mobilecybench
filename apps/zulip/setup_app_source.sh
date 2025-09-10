#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
ANDROID_HOME="${HOME}/.android-sdk"
source "$ROOT_DIR/utils/android.sh"

check_prerequisites() {
    echo "Checking if Docker is installed. Docker is required to build the zulip app."
    if command -v docker >/dev/null 2>&1; then
        echo "Docker is installed."
    else
        echo "ERROR: Docker is not installed."
        echo "Please install Docker first."
        exit 1
    fi

    echo "Prerequisites verified."
}

build_zulip() {
    echo "Building zulip app with flutter docker container..."

    # We use the beta version of flutter because the stable version fails due to Dart version mismatch:

    # The current Dart SDK version is 3.9.0.
    # Because zulip requires SDK version >=3.10.0-71.0.dev <4.0.0, version solving failed.
    # You can try the following suggestion to make the pubspec resolve:
    # * Try using the Flutter SDK version: 3.36.0-0.4.pre. 
    # Failed to update packages.

docker run --rm --platform=linux/amd64 \
  --memory=8g --cpus=4 \
  -v "$PWD":/app -w /app \
  -v "$HOME/.gradle":/root/.gradle \
  -v "$HOME/.pub-cache":/root/.pub-cache \
  -v "$HOME/.android":/root/.android \
  -e GRADLE_OPTS="-Xmx2g -Dorg.gradle.daemon=false -Dfile.encoding=UTF-8" \
  -e JAVA_TOOL_OPTIONS="-Xmx2g" \
  ghcr.io/cirruslabs/flutter:beta \
  bash -lc '
    set -euo pipefail
    SDKMGR=/opt/android-sdk-linux/cmdline-tools/latest/bin/sdkmanager
    yes | "$SDKMGR" --licenses >/dev/null
    "$SDKMGR" \
      "platform-tools" \
      "platforms;android-33" \
      "platforms;android-34" \
      "platforms;android-36" \
      "build-tools;35.0.0" \
      "ndk;27.0.12077973"

    # Ensure Gradle daemon is off + modest heap
    if [ -f android/gradle.properties ]; then
      grep -q "^org.gradle.daemon=" android/gradle.properties || \
        printf "\norg.gradle.daemon=false\n" >> android/gradle.properties
      grep -q "^org.gradle.workers.max=" android/gradle.properties || \
        printf "org.gradle.workers.max=2\n" >> android/gradle.properties
      grep -q "^org.gradle.jvmargs=" android/gradle.properties || \
        printf "org.gradle.jvmargs=-Xmx2g -Dfile.encoding=UTF-8\n" >> android/gradle.properties
      grep -q "^kotlin.daemon.jvmargs=" android/gradle.properties || \
        printf "kotlin.daemon.jvmargs=-Xmx1g\n" >> android/gradle.properties
    else
      cat > android/gradle.properties <<EOF
org.gradle.daemon=false
org.gradle.workers.max=2
org.gradle.jvmargs=-Xmx2g -Dfile.encoding=UTF-8
kotlin.daemon.jvmargs=-Xmx1g
EOF
    fi

    flutter pub get
    # Clean to avoid stale state if a prior OOM killed the daemon mid-task
    (cd android && ./gradlew clean --no-daemon)
    flutter build apk --release
  '
    
    echo "Built app APK."
}

# TODO: INSTALL SDK

main() {    
    echo "Setting up zulip Android"

    root_dir="$(pwd)"
    cd codebase/

    check_prerequisites
    build_zulip

    # TODO: INSTALL SDK

    echo "Setup complete! Zulip is ready for testing."
}

# Run main function
main "$@"