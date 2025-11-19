#!/usr/bin/env bash
# Grocy Android build script
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_PREFIX="[setup_app_source]"
CODEBASE_DIR="$SCRIPT_DIR/codebase"
APK_DIR="$SCRIPT_DIR/apk"
METADATA_FILE="$SCRIPT_DIR/metadata.json"

info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*" >&2; }
error(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*"; exit 1; }

# Load Java version and SDK from metadata.json
load_metadata() {
  if [ ! -f "$METADATA_FILE" ]; then
    error "metadata.json not found at $METADATA_FILE"
  fi

  REQUIRED_JAVA_VERSION=$(python3 -c "import json; print(json.load(open('$METADATA_FILE'))['java'])" 2>/dev/null || echo "17")
  TARGET_SDK=$(python3 -c "import json; print(json.load(open('$METADATA_FILE'))['sdk'])" 2>/dev/null || echo "34")
  info "Required Java version from metadata.json: $REQUIRED_JAVA_VERSION"
  info "Target SDK from metadata.json: $TARGET_SDK"
}

# --- Checks ---
check_prerequisites() {
  command -v java >/dev/null 2>&1 || error "Java not found"
  [ -d "$CODEBASE_DIR" ] || error "Codebase not found: $CODEBASE_DIR"
  [ -f "$CODEBASE_DIR/gradlew" ] || error "gradlew missing"

  # Setup Java (prefer Homebrew installation)
  if [ -d "/opt/homebrew/opt/openjdk@${REQUIRED_JAVA_VERSION}" ]; then
    export JAVA_HOME="/opt/homebrew/opt/openjdk@${REQUIRED_JAVA_VERSION}/libexec/openjdk.jdk/Contents/Home"
    export PATH="$JAVA_HOME/bin:$PATH"
  elif command -v /usr/libexec/java_home >/dev/null 2>&1; then
    JAVA_HOME="$(/usr/libexec/java_home -v ${REQUIRED_JAVA_VERSION} 2>/dev/null || /usr/libexec/java_home 2>/dev/null || true)"
    [ -n "$JAVA_HOME" ] && export JAVA_HOME && export PATH="$JAVA_HOME/bin:$PATH"
  fi

  # Android SDK detection
  if [ -z "${ANDROID_SDK_ROOT:-}" ]; then
    for d in "$HOME/.android-sdk" "$HOME/Library/Android/sdk" "/usr/local/share/android-sdk"; do
      if [ -d "$d" ]; then
        export ANDROID_SDK_ROOT="$d"
        break
      fi
    done
  fi
  export ANDROID_HOME="${ANDROID_SDK_ROOT:-}"

  chmod +x "$CODEBASE_DIR/gradlew" 2>/dev/null || true
}


# --- Environment setup ---
setup_environment() {
  export GRADLE_OPTS="-Xmx2048m -Dorg.gradle.jvmargs='-Xmx2048m' -Dorg.gradle.parallel=false -Dorg.gradle.caching=true"
  [ -n "${ANDROID_SDK_ROOT:-}" ] && printf 'sdk.dir=%s\n' "$ANDROID_SDK_ROOT" > "$CODEBASE_DIR/local.properties" || true
}


# --- Configure release signing ---
configure_release_signing() {
  cd "$CODEBASE_DIR"
  BUILD_GRADLE="app/build.gradle"

  # Skip if already configured
  grep -q "signingConfig.*signingConfigs.debug" "$BUILD_GRADLE" 2>/dev/null && cd - >/dev/null && return 0

  # Add debug signing to release build
  release_line=$(grep -n "^\s*release\s*{" "$BUILD_GRADLE" | head -1 | cut -d: -f1)
  [ -n "$release_line" ] && awk -v line="$release_line" 'NR == line {print $0; print "            signingConfig signingConfigs.debug"; next} {print}' "$BUILD_GRADLE" > "$BUILD_GRADLE.tmp" && mv "$BUILD_GRADLE.tmp" "$BUILD_GRADLE"

  cd - >/dev/null
}

# --- Build ---
build_grocy() {
  info "Building release APK..."
  cd "$CODEBASE_DIR"
  ./gradlew --no-daemon --max-workers=1 :app:assembleRelease -x test -x lint -x check || error "Build failed"
  cd - >/dev/null
}

# --- Export APK ---
export_artifacts() {
  # Find release APK (prefer universal, then arm64, then any)
  apk=$(find "$CODEBASE_DIR/app/build/outputs/apk/release" -name "*.apk" -print 2>/dev/null | head -n 1)
  [ -z "$apk" ] && error "No release APK found"

  mkdir -p "$APK_DIR"
  cp -f "$apk" "$APK_DIR/grocy.apk"
  info "APK ready: $APK_DIR/grocy.apk"
}

# --- Main ---
main() {
  load_metadata
  check_prerequisites
  setup_environment
  configure_release_signing
  build_grocy
  export_artifacts
}

main "$@"

