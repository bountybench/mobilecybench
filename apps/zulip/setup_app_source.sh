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
    ghcr.io/cirruslabs/flutter:beta \
    sh -c "flutter pub get && flutter build apk --release"
    
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