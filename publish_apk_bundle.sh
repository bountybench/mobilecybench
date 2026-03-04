#!/bin/bash
#
# Publish APK bundle to GitHub release
#
# Usage: ./publish_apk_bundle.sh apps/<app_name>

set -e

if [ -z "$1" ]; then
    echo "Usage: $0 apps/<app_name>"
    echo "Example: $0 apps/owncloud-android"
    exit 1
fi

APP_DIR="$1"
APP_NAME=$(basename "$APP_DIR")
APK_DIR="$APP_DIR/apk"
REPO="bountybench/mobilecybench"

if [ ! -d "$APK_DIR" ]; then
    echo "Error: $APK_DIR not found"
    exit 1
fi

# Check for APKs
if [ -z "$(find "$APK_DIR" -maxdepth 1 -name '*.apk' -type f 2>/dev/null)" ]; then
    echo "Error: No APKs found in $APK_DIR"
    exit 1
fi

# Find next version number
LATEST=$(gh release list --repo "$REPO" --json tagName --jq '.[].tagName' 2>/dev/null | grep "^apk-$APP_NAME-v" | sort -V | tail -1)
if [ -n "$LATEST" ]; then
    CURRENT_VERSION=$(echo "$LATEST" | sed "s/apk-$APP_NAME-v//")
    NEXT_VERSION=$((CURRENT_VERSION + 1))
else
    NEXT_VERSION=0
fi
TAG="apk-$APP_NAME-v$NEXT_VERSION"

echo "App: $APP_NAME"
echo "Tag: $TAG"
echo ""

# Create zip
ZIP_FILE="$APP_DIR/apk-bundle.zip"
pushd "$APP_DIR" > /dev/null
zip -r apk-bundle.zip apk/
popd > /dev/null

echo ""
echo "Uploading to GitHub release..."
gh release create "$TAG" "$ZIP_FILE" \
    --repo "$REPO" \
    --title "$TAG" \
    --notes "APK bundle for $APP_NAME (version $NEXT_VERSION)"

URL="https://github.com/$REPO/releases/download/$TAG/apk-bundle.zip"
# Update metadata.json
METADATA="$APP_DIR/metadata.json"
if [ -f "$METADATA" ]; then
    jq --arg url "$URL" '.download_link = $url' "$METADATA" > "$METADATA.tmp" && mv "$METADATA.tmp" "$METADATA"
    echo "Updated $METADATA with download_link"
fi

rm "$ZIP_FILE"
echo ""
echo "Done! Download URL:"
echo "$URL"
