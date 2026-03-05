#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

./gradlew clean
./gradlew packageGenericReleaseUniversalApk --no-daemon

cp app/build/outputs/apk_from_bundle/genericRelease/*-generic-release-universal-unsigned.apk "$SCRIPT_DIR/unsigned.apk"
