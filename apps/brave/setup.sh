#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_NAME="com.brave.browser"

echo "Setting up Brave browser..."

# 1. Download APK if not exists
if [[ ! -f "$SCRIPT_DIR/apk/brave.apk" ]]; then
    echo "Downloading Brave APK..."
    mkdir -p "$SCRIPT_DIR/apk"
    curl -L -o "$SCRIPT_DIR/apk/brave.apk" "https://github.com/brave/brave-browser/releases/download/v1.84.119/BraveMonox64.apk"
fi

# 2. Install APK (ignore errors)
echo "Installing Brave APK..."
adb uninstall "$PACKAGE_NAME" 2>/dev/null || true
adb install "$SCRIPT_DIR/apk/brave.apk"

# 3. Simple verification
echo "Verifying installation..."
if adb shell pm list packages | grep -q "$PACKAGE_NAME"; then
    echo "✓ Brave installed successfully"
else
    echo "✗ Brave installation failed"
    exit 1
fi

# 4. Optional simple launch (don't fail if it doesn't work)
echo "Attempting to launch Brave..."
adb shell monkey -p "$PACKAGE_NAME" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
echo "Setup complete!"