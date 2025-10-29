#!/bin/bash
set -euo pipefail

# Get metadata
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
METADATA_FILE="$SCRIPT_DIR/metadata.json"

# Extract download link from metadata.json
DOWNLOAD_LINK=$(python3 -c "import json; print(json.load(open('$METADATA_FILE'))['download_link'])")

# Create apk directory
mkdir -p "$SCRIPT_DIR/apk"

# Download APK
echo "[INFO] Downloading APK from: $DOWNLOAD_LINK"
curl -L "$DOWNLOAD_LINK" -o "$SCRIPT_DIR/apk/ankidroid.apk"

echo "[INFO] APK downloaded successfully to apk/ankidroid.apk"
ls -lh "$SCRIPT_DIR/apk/ankidroid.apk"
