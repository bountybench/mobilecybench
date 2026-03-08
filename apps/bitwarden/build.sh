#!/bin/bash
set -e

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$APP_DIR/../../" && pwd)"
CODEBASE_DIR="$APP_DIR/codebase"

# Bitwarden specific: create user.properties if missing
create_user_properties() {
    USER_PROPERTIES="$CODEBASE_DIR/user.properties"
    if [ ! -f "$USER_PROPERTIES" ]; then
        echo "[INFO] Creating user.properties in codebase/"
        # In CI, GITHUB_TOKEN should be set. Locally it might prompt if not careful, 
        # but for build.sh we assume environment is set or we use a dummy if just checking structure.
        if [ -z "${GITHUB_TOKEN:-}" ]; then
            echo "[WARNING] GITHUB_TOKEN not set. Build might fail if it needs to fetch packages."
            echo "gitHubToken=dummy_token" > "$USER_PROPERTIES"
        else
            echo "[INFO] Using GITHUB_TOKEN from environment."
            echo "gitHubToken=$GITHUB_TOKEN" > "$USER_PROPERTIES"
        fi
        echo "localSdk=false" >> "$USER_PROPERTIES"
        echo "[INFO] user.properties created."
    else
        echo "[INFO] user.properties already exists."
    fi
}

echo "=== Building Bitwarden ==="

create_user_properties

# Use the universal build_apk.sh script
# Bitwarden uses a specific variant: assembleFdroidDebug
export GRADLE_TASK=":app:assembleFdroidDebug"
# The output APK name typically follows the pattern: app-fdroid-debug.apk or similar
# Based on setup_app.sh, it expects it at codebase/app/build/outputs/apk/fdroid/debug/
# We'll let build_apk.sh handle the heavy lifting.

bash "$ROOT_DIR/build_apk.sh" "$APP_DIR"

echo "=== Bitwarden Build Finished ==="
