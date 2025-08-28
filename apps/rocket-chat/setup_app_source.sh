#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# dependencies
ensure_js_deps() {
  echo "Installing JavaScript dependencies..."
  cd "$SCRIPT_DIR/codebase"

  export CI=1

  # always use yarn
  if command -v corepack >/dev/null 2>&1; then
    corepack enable >/dev/null 2>&1 || true
    corepack prepare yarn@1.22.22 --activate --yes >/dev/null 2>&1 || true
  fi

  # if both lockfiles exist, prefer yarn and remove package-lock.json to avoid npm picking it up
  if [[ -f package-lock.json ]]; then
    echo "[INFO] Removing package-lock.json to avoid npm; using yarn.lock"
    rm -f package-lock.json
  fi

  if ! command -v yarn >/dev/null 2>&1; then
    echo "[ERROR] yarn not found (after corepack). Install yarn or enable corepack."
    exit 1
  fi

  echo "Using yarn (v$(yarn -v)) with yarn.lock"
  yarn install --frozen-lockfile --silent
}

echo "Building Rocket.Chat Android from source..."

ensure_js_deps

cd "$SCRIPT_DIR/codebase/android"

./gradlew --no-daemon clean
./gradlew --no-daemon assembleDebug

cp "$SCRIPT_DIR/codebase/android/app/build/outputs/apk/official/debug/app-official-debug.apk" "$SCRIPT_DIR/rocket-chat.apk"

echo "Build completed successfully."