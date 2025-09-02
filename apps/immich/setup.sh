#!/usr/bin/env bash
# Immich setup script
# 1. Verify prerequisites (docker, adb)
# 2. Start backend server (docker-compose)
# 3. Build app unless --fast is given
# 4. Install on emulator/device
# 5. Launch app and verify

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_SOURCE_SCRIPT="${SCRIPT_DIR}/setup_app_source.sh"
CODEBASE_DIR="${SCRIPT_DIR}/codebase/mobile"
LOG_PREFIX="[setup]"

TARGET_PACKAGE="app.alextran.immich"
SKIP_BUILD="false"
LAUNCH_SLEEP=3

info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*" >&2; }
fail(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*" >&2; exit 1; }
command_exists(){ command -v "$1" >/dev/null 2>&1; }

parse_args(){
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --fast|-f) SKIP_BUILD="true"; shift ;;
      --help|-h)
        echo "Usage: ./setup.sh [--fast] [--help]"
        exit 0 ;;
      *) warn "Unknown arg: $1"; shift ;;
    esac
  done
  if [[ "${FAST:-0}" == "1" ]]; then SKIP_BUILD="true"; fi
}

ensure_prereqs(){
  info "Checking prerequisites"
  command_exists docker || fail "docker is required"
  command_exists adb || fail "adb is required"
  info "Prerequisites OK"
}

ensure_device_ready() {
  info "Checking for connected Android device/emulator..."
  if ! adb get-state >/dev/null 2>&1; then
    fail "No adb device detected; please start an emulator first."
  fi
  info "ADB device detected and ready."
}

start_backend(){
  info "Starting Immich backend..."
  (cd "$SCRIPT_DIR" && docker network create shared_net || true && docker compose up -d)
  info "Backend started at http://localhost:2283"
}

build_app(){
  if [[ "$SKIP_BUILD" == "true" ]]; then
    info "Skipping build (--fast)"
    return
  fi
  if [[ ! -x "$APP_SOURCE_SCRIPT" ]]; then
    fail "App source build script missing: $APP_SOURCE_SCRIPT"
  fi
  "$APP_SOURCE_SCRIPT"
}

install_app(){
  info "Installing Immich APK"
  adb wait-for-device
  local apk="$CODEBASE_DIR/build/app/outputs/flutter-apk/app-release.apk"
  [[ -f "$apk" ]] || fail "APK not found at $apk"
  adb uninstall "$TARGET_PACKAGE" >/dev/null 2>&1 || true
  adb install -r "$apk" || fail "Failed to install APK"
  info "Immich installed"
}

launch_app(){
  info "Launching Immich"
  adb shell monkey -p "$TARGET_PACKAGE" -c android.intent.category.LAUNCHER 1
  sleep $LAUNCH_SLEEP
  if adb shell dumpsys window | grep -q "mCurrentFocus.*$TARGET_PACKAGE"; then
    info "Immich launched successfully"
  else
    warn "Immich may not have focus"
  fi
}

summary(){
  info "Setup complete 🎉"
  info "Backend: http://localhost:2283"
  info "App: $TARGET_PACKAGE installed and launched"
}

main(){
  parse_args "$@"
  ensure_prereqs
  start_backend
  build_app
  ensure_device_ready
  install_app
  launch_app
  summary
}

main "$@"
