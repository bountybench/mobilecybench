#!/usr/bin/env bash
# Builds the Immich Flutter app from source (no emulator).
# Schema role: CI step before emulator is started.

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODEBASE_DIR="$SCRIPT_DIR/codebase/mobile"
LOG_PREFIX="[setup_app_source]"
LOG_FILE="${SCRIPT_DIR}/setup_app_source.log"

# Duplicate output to console and log
exec > >(tee -a "$LOG_FILE") 2>&1

info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*"; }
fail(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*"; exit 1; }
command_exists(){ command -v "$1" >/dev/null 2>&1; }

check_prerequisites() {
    info "Checking prerequisites..."

    # Flutter via FVM
    if command_exists fvm; then
        info "FVM found: $(fvm --version)"
    elif command_exists flutter; then
        warn "FVM not found, using system Flutter: $(flutter --version)"
    else
        fail "Flutter/FVM not found. Install Flutter via FVM."
    fi

    # Dart
    if ! command_exists dart; then
        fail "Dart SDK not found (should come with Flutter)."
    fi

    info "Prerequisites verified."
}

setup_environment() {
    info "Setting up build environment..."

    cd "$CODEBASE_DIR"

    # Run pub get
    info "Fetching Flutter dependencies..."
    if command_exists fvm; then
        fvm flutter pub get
    else
        flutter pub get
    fi

    # Generate translations
    info "Generating translation files..."
    if make translation; then
        info "✅ Translations generated with make."
    else
        warn "⚠️  make translation failed; running fallback Dart commands..."
        dart run easy_localization:generate -S ../i18n -O lib/generated
        dart run bin/generate_keys.dart
        info "✅ Translations generated via fallback."
    fi

    info "Environment setup complete."
}

build_immich() {
    info "Building Immich APK..."

    if command_exists fvm; then
        fvm flutter build apk --release
    else
        flutter build apk --release
    fi

    APK_PATH="$CODEBASE_DIR/build/app/outputs/flutter-apk/app-release.apk"
    if [[ -f "$APK_PATH" ]]; then
        info "✅ Build complete: $APK_PATH"
    else
        fail "❌ APK not found after build."
    fi
}

main() {
    info "Immich Android Source Build"
    echo "============================"

    if [[ ! -d "$CODEBASE_DIR" ]]; then
        fail "Immich codebase not found at $CODEBASE_DIR"
    fi

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
