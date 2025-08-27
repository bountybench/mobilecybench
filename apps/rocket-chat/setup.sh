#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Prefer CI Android SDK if provided
if [[ -n "${ANDROID_SDK_ROOT:-}" ]]; then
  ANDROID_HOME="$ANDROID_SDK_ROOT"
elif [[ -n "${ANDROID_HOME:-}" ]]; then
  ANDROID_HOME="$ANDROID_HOME"
else
  ANDROID_HOME="${HOME}/.android-sdk"
fi

check_prerequisites() {
  echo "Checking prerequisites..."

  # Java 17
  if ! command -v java >/dev/null 2>&1; then
    echo "[ERROR] Java not found. Please install Java 17." >&2
    exit 1
  fi

  # Android SDK
  if [[ ! -d "$ANDROID_HOME" ]]; then
    echo "[ERROR] Android SDK not found at $ANDROID_HOME"
    exit 1
  fi

  echo "Prerequisites verified."
}

setup_environment() {
  echo "Setting up build environment..."

  # ensure java
  if [[ -n "${JAVA_HOME:-}" ]]; then
    echo "Using JAVA_HOME=$JAVA_HOME"
    export JAVA_HOME
    export PATH="$JAVA_HOME/bin:$PATH"
  elif [[ -d "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home" ]]; then
    echo "Using Homebrew OpenJDK 17"
    export JAVA_HOME="/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"
    export PATH="$JAVA_HOME/bin:$PATH"
  else
    echo "Using system Java"
  fi

  # Android SDK
  export ANDROID_HOME="$ANDROID_HOME"
  export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/emulator:$PATH"

  # get corepack for Yarn
  if command -v corepack >/dev/null 2>&1; then
    corepack enable >/dev/null 2>&1 || true
    corepack prepare yarn@1.22.22 --activate --yes >/dev/null 2>&1 || true
  fi

  # local.properties for Gradle
  echo "sdk.dir=$ANDROID_HOME" > "$SCRIPT_DIR/local.properties"
  echo "Environment configured."
}

# dependencies
ensure_js_deps() {
  echo "Installing JavaScript dependencies..."
  cd "$SCRIPT_DIR/codebase"

  # accept install every time
  export CI=1

  # if we have Corepack, make sure Yarn 1.x is activated silently
  if command -v corepack >/dev/null 2>&1; then
    corepack prepare yarn@1.22.22 --activate --yes >/dev/null 2>&1 || true
  fi

  yarn install --frozen-lockfile --silent
}

get_aapt() {
  local bt_dir="$(ls -1 "${ANDROID_HOME}/build-tools" 2>/dev/null | sort -V | tail -n1 || true)"
  if [[ -n "$bt_dir" && -x "${ANDROID_HOME}/build-tools/${bt_dir}/aapt" ]]; then
    echo "${ANDROID_HOME}/build-tools/${bt_dir}/aapt"; return 0
  fi
  command -v aapt >/dev/null 2>&1 && { command -v aapt; return 0; }
}

start_server() {
  echo "Starting Rocket.Chat server (docker-compose)…"
  pushd "$SCRIPT_DIR" >/dev/null
  docker compose up -d
  echo "Waiting for Rocket.Chat to be healthy at http://localhost:3000 …"
  for i in {1..60}; do
    if curl -fsS http://localhost:3000/api/info >/dev/null 2>&1; then
      echo "Rocket.Chat is up."
      popd >/dev/null
      return 0
    fi
    sleep 2
  done
  echo "[ERROR] Rocket.Chat server failed to start." >&2
  popd >/dev/null
  exit 1
}

build_and_install_rocket_chat() {
  echo "Building Rocket.Chat Android from source..."
  cd "$SCRIPT_DIR/codebase/android"
  ./gradlew --no-daemon clean && ./gradlew --no-daemon assembleDebug
  echo "Build completed successfully. Installing Rocket.Chat on Android emulator..."

  if ! adb devices | grep -E "device$|emulator" >/dev/null; then
    echo "No Android emulator/device found. Start it, then re-run."
    exit 1
  fi

  local APK_PATH="$SCRIPT_DIR/codebase/android/app/build/outputs/apk/official/debug/app-official-debug.apk"
  local PKG="chat.rocket.reactnative"

  if [[ -z "${APK_PATH:-}" || ! -f "$APK_PATH" ]]; then
    echo "[ERROR] Could not locate debug APK to install. Available APKs:"
    find "$SCRIPT_DIR/codebase/android" -name "*.apk" -type f 2>/dev/null | head -10
    exit 1
  fi

  echo "Found APK: $APK_PATH"
  adb install -r "$APK_PATH"
  echo "Rocket.Chat installed successfully. Launching Rocket.Chat in emulator..."
  adb shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 || true
}

seed_data() {
  echo "Seeding Rocket.Chat data (host)…"

  # wait for the server on the host port
  for i in {1..60}; do
    if curl -fsS http://localhost:3000/api/info >/dev/null 2>&1; then
      break
    fi
    sleep 2
  done

  # ensure deps (jq/curl) exist; bail with a helpful message if not
  if ! command -v jq >/dev/null 2>&1 || ! command -v curl >/dev/null 2>&1; then
    echo "[ERROR] jq and/or curl not found on host. Install with: brew install jq curl" >&2
    exit 1
  fi

  # run the seeder against localhost
  RC_URL="http://localhost:3000" \
  ADMIN_USERNAME="admin" \
  ADMIN_PASS="admin123" \
  "$SCRIPT_DIR/seed.sh"

  echo "Seeding complete."
}

main() {
  echo "Rocket.Chat Android Setup"

  # ensure codebase
  if [[ ! -d "$SCRIPT_DIR/codebase" ]]; then
    echo "codebase/ not found. Make sure the Rocket.Chat repo is at apps/rocket-chat/codebase"
    exit 1
  fi

  cd "$SCRIPT_DIR/codebase" && git checkout v1.2.1
  cd -

  check_prerequisites
  setup_environment
  ensure_js_deps
  start_server
  build_and_install_rocket_chat
  seed_data

  echo "Setup complete! Rocket.Chat is ready for testing."
}

main