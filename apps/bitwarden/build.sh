#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

# Create user.properties if missing (requires GITHUB_TOKEN)
if [[ ! -f "user.properties" ]]; then
    if [[ -z "$GITHUB_TOKEN" ]]; then
        echo "ERROR: GITHUB_TOKEN environment variable required for Bitwarden build"
        exit 1
    fi
    cat > user.properties <<EOF
gitHubToken=$GITHUB_TOKEN
localSdk=false
EOF
fi

./gradlew :app:assembleFdroidDebug --console=plain --no-daemon

cp app/build/outputs/apk/fdroid/debug/*.apk "$SCRIPT_DIR/unsigned.apk"
