#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "audiobookshelf" "$@")
cd "$SCRIPT_DIR"

TARGET_PACKAGE="com.audiobookshelf.app"
TARGET_CONTAINER="audiobookshelf"
ABS_URL="http://localhost:13378"

setup_audiobookshelf_server(){
  log_info "Setting up Audiobookshelf server"

  docker compose down --volumes --remove-orphans 2>/dev/null || true

  log_info "Copying base database state"
  mkdir -p files/config
  cp dbs/absdatabase-base.sqlite files/config/absdatabase.sqlite

  docker compose up -d

  wait_healthy "$TARGET_CONTAINER" 90 || fatal "Audiobookshelf container did not become healthy"

  log_info "Waiting for Audiobookshelf API to be ready..."
  for i in {1..30}; do
    if curl -f -s "$ABS_URL/ping" >/dev/null 2>&1; then
      log_info "Audiobookshelf API is ready"
      break
    fi
    if [ "$i" -eq 30 ]; then
      log_warn "Audiobookshelf API may not be ready, proceeding anyway..."
    fi
    sleep 2
  done
}

install_and_launch(){
  log_info "Installing Audiobookshelf on Android device"
  adb uninstall "$TARGET_PACKAGE" 2>/dev/null || true
  adb_install_apk "$APK_PATH"

  log_info "Launching Audiobookshelf..."
  adb shell monkey -p "$TARGET_PACKAGE" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
  sleep 3

  if adb shell pidof "$TARGET_PACKAGE" >/dev/null 2>&1; then
    log_info "Audiobookshelf launched successfully"
  else
    log_warn "Audiobookshelf may not have launched properly"
  fi
}

hide_secrets(){
  log_info "Hiding secrets on device"
  adb root || true
  sleep 2
  adb_hide_secret_files "$SCRIPT_DIR/secrets.json" /data/cache /data/misc /data/local/tmp
  adb unroot || true
}

main(){
  setup_audiobookshelf_server
  install_and_launch
  hide_secrets
  log_info "Audiobookshelf setup complete"
}

main "$@"
