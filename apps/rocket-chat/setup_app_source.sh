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

  echo "Using yarn with yarn.lock"
  yarn install --frozen-lockfile --silent
}

echo "Building Rocket.Chat Android from source..."

ensure_js_deps

cd "$SCRIPT_DIR/codebase/android"

# Detect the emulator/device ABI (falls back to host arch)
EMULATOR_ABI=""
if command -v adb >/dev/null 2>&1 && adb get-state >/dev/null 2>&1; then
  EMULATOR_ABI="$(adb shell getprop ro.product.cpu.abi | tr -d '\r')"
fi
if [[ -z "$EMULATOR_ABI" ]]; then
  case "$(uname -m)" in
    arm64|aarch64) EMULATOR_ABI="arm64-v8a" ;;
    x86_64|amd64)  EMULATOR_ABI="x86_64" ;;
    *)             EMULATOR_ABI="x86_64" ;;
  esac
fi
echo "Target ABI: $EMULATOR_ABI"

# Gradle perf/caching knobs (idempotent append)
PROP_FILE="gradle.properties"
if ! grep -q "org.gradle.daemon" "$PROP_FILE" 2>/dev/null; then
  cat >> "$PROP_FILE" <<'EOF'
org.gradle.daemon=true
org.gradle.caching=true
org.gradle.parallel=true
org.gradle.configureondemand=true
org.gradle.jvmargs=-Xmx3g -XX:MaxMetaspaceSize=1g -Dkotlin.daemon.jvm.options=-Xmx1g
org.gradle.workers.max=2
reactNativeArchitectures=
EOF
fi

# Build just the OfficialDebug variant for the detected ABI
./gradlew --no-daemon --build-cache --parallel --max-workers=2 \
  assembleOfficialDebug \
  -PreactNativeArchitectures="$EMULATOR_ABI" \
  -Dorg.gradle.workers.max=2

# Copy the APK
APK_OUT="$SCRIPT_DIR/codebase/android/app/build/outputs/apk/official/debug/app-official-debug.apk"
cp "$APK_OUT" "$SCRIPT_DIR/rocket-chat.apk"
echo "Copied APK to $SCRIPT_DIR/rocket-chat.apk"