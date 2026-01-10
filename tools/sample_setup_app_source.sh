#!/usr/bin/env bash
# Example setup_app_source.sh using shared helpers.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

# Source shared helpers
source "$ROOT_DIR/tools/setup_helpers.sh"

# Configuration (adjust per app)
JAVA_VERSION="17"                # or 21 if required
PROJECT_DIR="$SCRIPT_DIR/codebase"
APK_OUT="$SCRIPT_DIR/apk/app.apk" # final artifact location

main() {
  info "Sample build starting"

  resolve_java "$JAVA_VERSION"
  resolve_android_sdk || warn "Proceeding without Android SDK; AGP may download components."

  write_local_properties "$PROJECT_DIR"
  ensure_gradlew "$PROJECT_DIR"

  cd "$PROJECT_DIR"
  ./gradlew assembleRelease

  apk_unsigned="$(pick_apk "$PROJECT_DIR" '*/release/*-unsigned.apk' '*/release/*.apk' '*/debug/*.apk' || true)"
  [[ -n "$apk_unsigned" ]] || error "No APK produced"

  # Sign if unsigned
  if [[ "$apk_unsigned" == *"-unsigned.apk" ]]; then
    apk_signed="$(sign_apk_debug "$apk_unsigned")"
  else
    apk_signed="$apk_unsigned"
  fi

  copy_apk "$apk_signed" "$APK_OUT"
  info "Sample build complete: $APK_OUT"
}

main "$@"
