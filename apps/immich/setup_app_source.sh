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

# ---- logging ----
exec > >(tee -a "$LOG_FILE") 2>&1
info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*"; }
fail(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*"; exit 1; }
command_exists(){ command -v "$1" >/dev/null 2>&1; }

# ---- Bootstrap FVM + Flutter (Linux) ----
bootstrap_fvm_and_flutter() {
  info "Bootstrapping FVM and Flutter toolchain (Linux)..."

  # Where `dart pub global` installs FVM
  export PATH="$HOME/.pub-cache/bin:$PATH"

  if ! command_exists fvm; then
    if ! command_exists dart; then
      info "Dart not found; installing Flutter SDK (stable) locally under ~/.flutter ..."
      FLUTTER_VERSION="${FLUTTER_VERSION:-3.24.0}"
      BASE_URL="https://storage.googleapis.com/flutter_infra_release/releases/stable/linux"
      TARBALL="flutter_linux_${FLUTTER_VERSION}-stable.tar.xz"
      DEST="$HOME/.flutter"
      TMP="$(mktemp -t flutter-${FLUTTER_VERSION}-XXXXXXXX.tar.xz)"

      # deps
      command -v curl >/dev/null 2>&1 || fail "curl not found"
      command -v tar  >/dev/null 2>&1 || fail "tar not found"
      command -v xz   >/dev/null 2>&1 || command -v xzcat >/dev/null 2>&1 || warn "xz utils not found; tar -xJf may fail"

      mkdir -p "$DEST"
      if [ ! -d "$DEST/flutter" ]; then
        curl -fL "${BASE_URL}/${TARBALL}" -o "$TMP"
        tar -xJf "$TMP" -C "$DEST"
        rm -f "$TMP"
      fi

      export PATH="$DEST/flutter/bin:$PATH"
      command_exists flutter || fail "Flutter not found after install"
      flutter --version
    fi

    # Now Dart should be available (bundled with Flutter)
    command_exists dart || fail "Dart still not found after Flutter install"

    info "Installing FVM via 'dart pub global activate fvm'..."
    dart pub global activate fvm >/dev/null
    export PATH="$HOME/.pub-cache/bin:$PATH"
    command_exists fvm || fail "FVM not on PATH after install."
  else
    info "FVM present: $(fvm --version)"
  fi

  # Ensure project Flutter via FVM
  [ -d "$CODEBASE_DIR" ] || fail "Immich codebase not found at $CODEBASE_DIR"

  pushd "$CODEBASE_DIR" >/dev/null
  if [ -f ".fvm/fvm_config.json" ]; then
    info "Using pinned Flutter from .fvm/fvm_config.json"
    fvm install
    fvm use
  else
    info "No .fvm config; using stable channel"
    fvm install stable
    fvm use stable
  fi
  fvm flutter --version
  fvm flutter doctor -v || true
  popd >/dev/null

  info "FVM + Flutter bootstrap complete."
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
  command_exists dart || fail "Dart SDK not found after bootstrap."
  info "Dart: $(dart --version 2>&1 | head -n1)"
  info "Prerequisites verified."
}

# ---- Prepare project ----
setup_environment() {
  info "Setting up build environment..."
  cd "$CODEBASE_DIR"

  info "Fetching Flutter dependencies..."
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
      dart run easy_localization:generate -S ../i18n -O lib/generated || true
      dart run bin/generate_keys.dart || true
      info "Fallback translation generation attempted."
    fi
  fi

  info "Environment setup complete."
}

# ---- Build APK ----
build_immich() {
  info "Building Immich APK (release)..."
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

  bootstrap_fvm_and_flutter
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
