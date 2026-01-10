#!/usr/bin/env bash
# Example Home Assistant setup_app_source.sh using shared helpers.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

# Default to the real app path; override via PROJECT_DIR if desired
: "${PROJECT_DIR:=$ROOT_DIR/apps/home-assistant-android/codebase}"
: "${APK_OUT:=$ROOT_DIR/apps/home-assistant-android/apk/home-assistant-android.apk}"
: "${JAVA_VERSION:=17}"
# expected to sit next to the app directory
: "${GMS_PATH:=$ROOT_DIR/apps/home-assistant-android/google-services.json}"

source "$ROOT_DIR/tools/setup_helpers.sh"

ensure_module_keystore() {
  local module_dir="$1"
  local ks="$module_dir/release_keystore.keystore"
  if [[ ! -f "$ks" ]]; then
    keytool -genkeypair -v -keystore "$ks" \
      -alias release -keyalg RSA -keysize 2048 -validity 10000 \
      -storepass android -keypass android \
      -dname "CN=Android Debug,O=Home Assistant,C=US"
    info "Created mock release keystore for $module_dir"
  fi
}

copy_google_services() {
  [[ -f "$GMS_PATH" ]] || error "google-services.json missing at $GMS_PATH"
  cp "$GMS_PATH" "$PROJECT_DIR/app/google-services.json"
  cp "$GMS_PATH" "$PROJECT_DIR/wear/google-services.json"
  cp "$GMS_PATH" "$PROJECT_DIR/automotive/google-services.json"
}

main() {
  info "Home Assistant sample build starting"

  resolve_java "$JAVA_VERSION"
  resolve_android_sdk || warn "Proceeding without Android SDK; AGP may bootstrap components."
  write_local_properties "$PROJECT_DIR"
  ensure_gradlew "$PROJECT_DIR"

  cd "$PROJECT_DIR"
  git submodule update --init --recursive

  ensure_module_keystore "app"
  ensure_module_keystore "wear"
  ensure_module_keystore "automotive"
  export KEYSTORE_PASSWORD="android"
  export KEYSTORE_ALIAS="release"
  export KEYSTORE_ALIAS_PASSWORD="android"

  copy_google_services

  ./gradlew --no-daemon clean
  ./gradlew --no-daemon --max-workers=1 \
    app:assembleMinimalRelease \
    -Dorg.gradle.jvmargs="-Xmx2048m" \
    -Dorg.gradle.parallel=false \
    -PnoLeakCanary \
    --write-locks

  apk_path="app/build/outputs/apk/minimal/release/app-minimal-release.apk"
  if [[ ! -f "$apk_path" ]]; then
    apk_path="$(pick_apk "$PROJECT_DIR" '*/minimal/release/*minimal*release*.apk' '*/release/*.apk' || true)"
  fi
  [[ -n "$apk_path" ]] || error "No APK produced"

  copy_apk "$apk_path" "$APK_OUT"
  info "Home Assistant sample build complete: $APK_OUT"
}

main "$@"
