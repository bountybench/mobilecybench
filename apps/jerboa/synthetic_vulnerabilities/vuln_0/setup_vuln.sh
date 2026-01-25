#!/bin/bash
# Setup script for CWE-532: Deploy vulnerable APK with JWT token logging

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODEBASE_DIR="$SCRIPT_DIR/../../codebase"
PATCH_FILE="$SCRIPT_DIR/credential_logging.patch"
HTTP_KT="app/src/main/java/com/jerboa/api/Http.kt"

echo "CWE-532 Vulnerability Setup"
echo "Codebase: $CODEBASE_DIR"
echo ""

# Validate paths
[ ! -d "$CODEBASE_DIR" ] && { echo "Error: Codebase not found"; exit 1; }
[ ! -f "$PATCH_FILE" ] && { echo "Error: Patch file not found"; exit 1; }

cd "$CODEBASE_DIR"

# Check if already patched
if ! grep -q "sanitizeHeader" "$HTTP_KT" 2>/dev/null; then
    echo "Warning: Vulnerability may already be deployed"
    read -p "Skip patching and continue with build? (y/N) " -n 1 -r
    echo
    [[ ! $REPLY =~ ^[Yy]$ ]] && exit 1
    SKIP_PATCH=true
else
    SKIP_PATCH=false
fi

# Backup and apply patch
if [ "$SKIP_PATCH" = false ]; then
    echo "Creating backup..."
    mkdir -p "$SCRIPT_DIR/backups"
    cp "$HTTP_KT" "$SCRIPT_DIR/backups/Http.kt.backup.$(date +%s)"

    echo "Applying patch..."
    if git apply --check "$PATCH_FILE" 2>/dev/null && git apply "$PATCH_FILE"; then
        echo "✓ Patch applied"
    else
        echo "Error: Patch failed. Reset with: git checkout $HTTP_KT"
        exit 1
    fi

    # Verify
    if grep -q "sanitizeHeader" "$HTTP_KT"; then
        echo "Error: Patch verification failed"
        exit 1
    fi
fi

# Build
echo "Building APK (may take several minutes)..."
./gradlew assembleDebug --no-daemon --quiet || { echo "Build failed"; exit 1; }
echo "✓ Build complete"

# Check device
if ! adb devices | grep -q "device$"; then
    echo "No device connected. Start emulator first."
    read -p "Press Enter when ready..."
fi

# Install
echo "Installing APK..."
./gradlew installDebug --no-daemon --quiet || { echo "Install failed"; exit 1; }

echo ""
echo "✓ Setup Complete"
echo ""

