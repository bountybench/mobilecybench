#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase/project"

./gradlew :app:assembleOssRelease --no-daemon

cp app/build/outputs/apk/oss/release/*-release-unsigned.apk "$SCRIPT_DIR/unsigned.apk"
