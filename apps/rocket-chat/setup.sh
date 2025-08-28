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

  # write local.properties
  ANDROID_DIR="$SCRIPT_DIR/codebase/android"
  mkdir -p "$ANDROID_DIR"
  echo "sdk.dir=$ANDROID_HOME" > "$ANDROID_DIR/local.properties"
  echo "Environment configured."
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
  docker compose up -d
  echo "Waiting for Rocket.Chat to be healthy at http://localhost:3000 …"
  for i in {1..80}; do
    if curl -fsS http://localhost:3000/api/info | jq '.success'; then
      echo "Rocket.Chat is up."
      break
    fi
    echo "."
    sleep 1
  done
  if ! curl -fsS http://localhost:3000/api/info | jq '.success'; then
    echo "[ERROR] Rocket.Chat did not start in time."
    exit 1
  fi
  echo "Rocket.Chat server is healthy."
}

install_rocket_chat() {
    APK_PATH="$SCRIPT_DIR/rocket-chat.apk"
    if [[ ! -f "$APK_PATH" ]]; then
        echo "[ERROR] APK not found at $APK_PATH"
        exit 1
    fi

    echo "Installing Rocket.Chat from $APK_PATH ..."
    adb install -r -d -g "$APK_PATH" || return 1
    echo "Installed successfully."

    # Launch Rocket.Chat (package + main activity)
    adb shell am start -n chat.rocket.reactnative/.MainActivity || {
        echo "[WARN] Direct launch failed, trying monkey..."
        adb shell monkey -p chat.rocket.reactnative -c android.intent.category.LAUNCHER 1
    }
}

seed_data() {
  echo "Seeding Rocket.Chat data (host)…"

  # wait for the server on the host port
  for i in {1..80}; do
    if curl -fsS http://localhost:3000/api/info | jq '.success'; then
      break
    fi
    echo "."
    sleep 1
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

}

main() {
  echo "Rocket.Chat Android Setup"

  # ensure codebase
  if [[ ! -d "$SCRIPT_DIR/codebase" ]]; then
    echo "codebase/ not found. Make sure the Rocket.Chat repo is at apps/rocket-chat/codebase"
    exit 1
  fi

  cd "$SCRIPT_DIR/codebase"
  git checkout develop || true
  git pull origin develop || true
  cd - >/dev/null

  check_prerequisites
  setup_environment
  start_server
  install_rocket_chat
  seed_data

  echo "Setup complete! Rocket.Chat is ready for testing."
}

main "$@"