#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

# Bitwarden specific: create user.properties if missing
# This is needed because the Bitwarden build requires a GitHub token 
# to fetch some dependencies from GitHub Packages.
USER_PROPERTIES="user.properties"
if [ ! -f "$USER_PROPERTIES" ]; then
    echo "[INFO] Creating user.properties in codebase/"
    if [ -z "${GITHUB_TOKEN:-}" ]; then
        echo "[WARNING] GITHUB_TOKEN not set. Build might fail."
        echo "gitHubToken=dummy_token" > "$USER_PROPERTIES"
    else
        echo "[INFO] Using GITHUB_TOKEN from environment."
        echo "gitHubToken=$GITHUB_TOKEN" > "$USER_PROPERTIES"
    fi
    echo "localSdk=false" >> "$USER_PROPERTIES"
fi

echo "=== Building Bitwarden (FdroidRelease) ==="

# Bitwarden MUST be built in Release mode for the benchmark.
# We use the Fdroid flavor as it is the most open-source compliant variant.
./gradlew :app:assembleFdroidRelease --no-daemon

# The output APK name for a release build
# We copy it to the root of the app directory as unsigned.apk for build_apk.sh to pick up
# Note: Release builds are often unsigned by default unless signing is configured in build.gradle.
# build_apk.sh will handle the final signing with the benchmark keystore.
if [ -f "app/build/outputs/apk/fdroid/release/app-fdroid-release-unsigned.apk" ]; then
    cp app/build/outputs/apk/fdroid/release/app-fdroid-release-unsigned.apk "$SCRIPT_DIR/unsigned.apk"
else
    # Fallback if the name differs
    cp app/build/outputs/apk/fdroid/release/app-fdroid-release.apk "$SCRIPT_DIR/unsigned.apk"
fi

echo "=== Bitwarden Build Finished ==="
