#!/usr/bin/env bash
# Builds the Immich Flutter app from source (no emulator).
# Intended for Linux CI/agents. Idempotently installs FVM + Flutter if missing.

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODEBASE_DIR="$SCRIPT_DIR/codebase/mobile"
LOG_PREFIX="[setup_app_source]"
LOG_FILE="${SCRIPT_DIR}/setup_app_source.log"

# Optional: INSTALL_ANDROID=true to attempt Android SDK bootstrap (best-effort)
INSTALL_ANDROID="${INSTALL_ANDROID:-false}"

# Use Flutter version that includes Dart >= 3.8.0
FLUTTER_VERSION="${FLUTTER_VERSION:-3.32.0}"

# ---- logging ----
exec > >(tee -a "$LOG_FILE") 2>&1
info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*"; }
fail(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*"; exit 1; }
command_exists(){ command -v "$1" >/dev/null 2>&1; }

# ---- Bootstrap FVM + Flutter (Linux) ----
bootstrap_prereqs() {
  info "Bootstrapping prerequisites (Flutter/FVM + npm)..."

  # --- npm / Node.js ---
  if ! command_exists npm; then
    info "npm not found; attempting to install Node.js LTS..."
    if command_exists apt-get; then
      curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
      sudo apt-get install -y nodejs
    elif command_exists yum; then
      curl -fsSL https://rpm.nodesource.com/setup_lts.x | sudo bash -
      sudo yum install -y nodejs
    else
      warn "Package manager not supported; please install Node.js/npm manually."
    fi
  else
    info "npm present: $(npm --version)"
  fi

  # install pnpm globally so pnpx is available (pnpm provides the pnpx shim)
  if ! command -v pnpx >/dev/null 2>&1; then
    info "Installing pnpm globally (provides pnpx)..."
    npm i -g pnpm@8
  fi

  # --- FVM + Flutter ---
  export PATH="$HOME/.pub-cache/bin:$PATH"

  if ! command_exists fvm; then
    if ! command_exists dart; then
      info "Dart not found; installing Flutter SDK ($FLUTTER_VERSION) locally under ~/.flutter ..."
      BASE_URL="https://storage.googleapis.com/flutter_infra_release/releases/stable/linux"
      TARBALL="flutter_linux_${FLUTTER_VERSION}-stable.tar.xz"
      DEST="$HOME/.flutter"
      TMP="$(mktemp -t flutter-${FLUTTER_VERSION}-XXXXXXXX.tar.xz)"

      mkdir -p "$DEST"
      if [ ! -d "$DEST/flutter" ]; then
        curl -fL "${BASE_URL}/${TARBALL}" -o "$TMP"
        tar -xJf "$TMP" -C "$DEST"
        rm -f "$TMP"
      fi
      export PATH="$DEST/flutter/bin:$PATH"
      flutter --version
    fi

    dart pub global activate fvm >/dev/null
    export PATH="$HOME/.pub-cache/bin:$PATH"
    command_exists fvm || fail "FVM not on PATH after install."
  else
    info "FVM present: $(fvm --version)"
  fi

  # Ensure we're in the right directory
  mkdir -p "$CODEBASE_DIR"
  pushd "$CODEBASE_DIR" >/dev/null
  
  # Always install the required Flutter version for Immich
  info "Installing Flutter $FLUTTER_VERSION for Immich compatibility..."
  fvm install "$FLUTTER_VERSION"
  fvm use "$FLUTTER_VERSION"
  
  # Verify the Dart version
  CURRENT_DART="$(fvm dart --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n1)"
  info "Using Dart version: $CURRENT_DART"
  
  fvm flutter --version
  fvm flutter doctor -v || true
  popd >/dev/null

  info "Bootstrap complete (npm + Flutter/FVM)."
}

# ---- Optional Android SDK (Linux best-effort) ----
maybe_install_android_sdk() {
  [ "$INSTALL_ANDROID" = "true" ] || { info "Skipping Android SDK install (INSTALL_ANDROID=false)."; return 0; }

  info "Attempting Android SDK bootstrap (Linux)..."
  if command_exists sdkmanager; then
    info "sdkmanager present."
  else
    export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-$HOME/android-sdk}"
    mkdir -p "$ANDROID_SDK_ROOT/cmdline-tools"
    if [ ! -d "$ANDROID_SDK_ROOT/cmdline-tools/latest" ]; then
      info "Installing Android cmdline-tools..."
      tmpzip="$(mktemp -t cmdline-tools-XXXXX.zip)"
      curl -sSL "https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip" -o "$tmpzip"
      mkdir -p "$ANDROID_SDK_ROOT/cmdline-tools/latest"
      unzip -q "$tmpzip" -d "$ANDROID_SDK_ROOT/cmdline-tools/latest"
      rm -f "$tmpzip"
    fi
    export PATH="$PATH:$ANDROID_SDK_ROOT/platform-tools:$ANDROID_SDK_ROOT/cmdline-tools/latest/bin"
  fi

  if command_exists sdkmanager; then
    yes | sdkmanager --licenses >/dev/null 2>&1 || true
    sdkmanager "platform-tools" "platforms;android-34" "build-tools;34.0.0" || \
      warn "sdkmanager package install failed; ensure network access and cmdline-tools are valid."
    info "ANDROID_SDK_ROOT=${ANDROID_SDK_ROOT:-unset}"
  else
    warn "sdkmanager still not found; APK build may fail without Android SDK."
  fi
}

# ---- Verify prerequisites after bootstrap ----
check_prerequisites() {
  info "Verifying prerequisites..."
  command_exists fvm || fail "FVM not found after bootstrap."
  info "FVM: $(fvm --version)"
  
  cd "$CODEBASE_DIR"
  
  # Check Dart version from FVM Flutter
  CURRENT_DART="$(fvm dart --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n1)"
  REQUIRED_DART="3.8.0"

  # Version comparison function
  version_ge() { 
    printf '%s\n%s\n' "$1" "$2" | sort -V -C 2>/dev/null
  }

  if [ -z "$CURRENT_DART" ]; then
    fail "Could not determine Dart version"
  fi

  if ! version_ge "$CURRENT_DART" "$REQUIRED_DART"; then
    fail "Dart $CURRENT_DART is below requirement ($REQUIRED_DART)"
  fi

  info "Flutter: $(fvm flutter --version | head -n1)"
  info "Dart:    $CURRENT_DART (>= $REQUIRED_DART required)"
  info "Prerequisites verified."
}

# ---- Prepare project ----
setup_environment() {
  info "Setting up build environment..."
  cd "$CODEBASE_DIR"

  info "Fetching Flutter dependencies..."
  # Set environment variables for CI
  export PUB_CACHE="$HOME/.pub-cache"
  export FLUTTER_ROOT="$HOME/.fvm/versions/$FLUTTER_VERSION"
  
  fvm flutter pub get

  info "Generating translation/localization files..."
  if make translation; then
    info "Translations generated with make."
  else
    warn "make translation failed; trying 'fvm flutter gen-l10n'..."
    if fvm flutter gen-l10n; then
      info "Translations generated via flutter gen-l10n."
    else
      warn "gen-l10n failed; attempting easy_localization fallback..."
      fvm dart run easy_localization:generate -S ../i18n -O lib/generated || true
      fvm dart run bin/generate_keys.dart || true
      info "Fallback translation generation attempted."
    fi
  fi

  info "Environment setup complete."
}

# ---- Build APK ----
build_immich() {
  info "Building Immich APK (release)..."
  cd "$CODEBASE_DIR"
  fvm flutter build apk --release

  local apk_path="$CODEBASE_DIR/build/app/outputs/flutter-apk/app-release.apk"
  if [[ -f "$apk_path" ]]; then
    info "✅ Build complete: $apk_path"
  else
    fail "APK not found after build."
  fi
}

main() {
  info "Immich Android Source Build"
  echo "============================"

  bootstrap_prereqs
  maybe_install_android_sdk
  check_prerequisites
  setup_environment
  build_immich

  echo ""
  echo "=========================================="
  info "Immich Build complete! APK is ready."
  echo "=========================================="
  echo ""
}

main "$@"