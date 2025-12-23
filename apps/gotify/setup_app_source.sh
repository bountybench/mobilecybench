#!/usr/bin/env bash
# Gotify Android build (light build with resource constraints)
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_PREFIX="[setup_app_source]"
CODEBASE_DIR="$SCRIPT_DIR/codebase"
APK_DIR="$SCRIPT_DIR/apk"

info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*" >&2; }
error(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*"; exit 1; }

# --- Checks ---
check_prerequisites() {
  command -v java >/dev/null 2>&1 || error "Java not found on PATH"
  [ -d "$CODEBASE_DIR" ] || error "Codebase not found: $CODEBASE_DIR"
  [ -f "$CODEBASE_DIR/gradlew" ] || error "gradlew missing in $CODEBASE_DIR"

  # Prefer Java 17, but allow Java 21+ (compatible with Android builds)
  java_version=$(java -version 2>&1 | head -n 1 | awk -F '"' '{print $2}' | awk -F '[._]' '{print $1}')
  if [ "$java_version" -lt "17" ] 2>/dev/null; then
    error "Java 17+ required, found: $java_version"
  elif [ "$java_version" -gt "17" ] 2>/dev/null; then
    warn "Java $java_version found (Java 17 preferred), proceeding..."
  fi

  # Try to use Java 17 if available on macOS
  if command -v /usr/libexec/java_home >/dev/null 2>&1; then
    JAVA_17_HOME="$(/usr/libexec/java_home -v 17 2>/dev/null || true)"
    if [ -n "$JAVA_17_HOME" ]; then
      export JAVA_HOME="$JAVA_17_HOME"
      export PATH="$JAVA_HOME/bin:$PATH"
      info "Using Java 17: $JAVA_HOME"
    else
      info "Java 17 not found, using Java $java_version"
    fi
  fi

  # Android SDK detection
  if [ -z "${ANDROID_HOME:-}" ] && [ -z "${ANDROID_SDK_ROOT:-}" ]; then
    for d in "$HOME/Library/Android/sdk" "$HOME/.android-sdk" "/usr/local/share/android-sdk" "/usr/local/lib/android/sdk"; do
      [ -d "$d" ] && ANDROID_HOME="$d" && break
    done
    export ANDROID_HOME="${ANDROID_HOME:-}"
  fi
  export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-}}"

  [ -n "${ANDROID_SDK_ROOT:-}" ] || warn "ANDROID_SDK_ROOT not set; proceeding (AGP may bootstrap)."

  chmod +x "$CODEBASE_DIR/gradlew" 2>/dev/null || true

  # Verify gradlew is executable
  if [ ! -x "$CODEBASE_DIR/gradlew" ]; then
    error "gradlew is not executable: $CODEBASE_DIR/gradlew"
  fi
}

# --- Print toolchain info ---
print_toolchain_info() {
  info "Toolchain versions:"
  cd "$CODEBASE_DIR"
  java -version || true
  ./gradlew --version || true
  cd - >/dev/null
}

# --- Environment setup ---
setup_environment() {
  info "Setting up light build environment..."

  # Light build settings - constrained resources
  export GRADLE_OPTS="-Xmx2048m -Dorg.gradle.jvmargs='-Xmx2048m' -Dorg.gradle.parallel=false -Dorg.gradle.caching=true"

  # Verify Android SDK android-35 platform
  if [ -n "${ANDROID_SDK_ROOT:-}" ]; then
    PLATFORM_DIR="$ANDROID_SDK_ROOT/platforms/android-35"
    BUILD_TOOLS_DIR="$ANDROID_SDK_ROOT/build-tools"

    if [ ! -d "$PLATFORM_DIR" ]; then
      error "Android SDK 35 platform not found at: $PLATFORM_DIR. Please install android-35 platform."
    fi

    if [ ! -d "$BUILD_TOOLS_DIR" ] || [ -z "$(find "$BUILD_TOOLS_DIR" -maxdepth 1 -type d -name "*35*" 2>/dev/null)" ]; then
      warn "Android build-tools for API 35 not found. Build may fail."
    fi

    info "Android SDK 35 platform verified"
  fi

  # Set local.properties if needed
  if [ -n "${ANDROID_SDK_ROOT:-}" ]; then
    if [ ! -f "$CODEBASE_DIR/local.properties" ] || ! grep -q '^sdk.dir=' "$CODEBASE_DIR/local.properties" 2>/dev/null; then
      printf 'sdk.dir=%s\n' "$ANDROID_SDK_ROOT" > "$CODEBASE_DIR/local.properties"
    fi
  fi
}

# --- Validate target SDK ---
validate_target_sdk() {
  info "Validating target SDK..."

  cd "$CODEBASE_DIR"

  # Check if targetSdk is 35 in build.gradle files
  target_sdk_found=false
  while IFS= read -r -d '' gradle_file; do
    if grep -q "targetSdk.*35\|targetSdkVersion.*35" "$gradle_file" 2>/dev/null; then
      target_sdk_found=true
      break
    fi
  done < <(find . -name "build.gradle*" -type f -print0)

  if [ "$target_sdk_found" = "false" ]; then
    error "Target SDK 35 not found in build.gradle files. Please update metadata.json and app configuration."
  fi

  info "Target SDK 35 validated"
  cd - >/dev/null
}

# --- Build ---
build_gotify() {
  info "Starting Gotify release build..."

  cd "$CODEBASE_DIR"

  # Light build with resource constraints
  set +e
  ./gradlew --no-daemon --max-workers=1 \
    :app:assembleRelease \
    -x test -x lint -x check
  rc=$?
  set -e

  if [ $rc -ne 0 ]; then
    error "Gradle build failed (rc=$rc)"
  fi

  cd - >/dev/null
}

# --- Export APK ---
export_artifacts() {
  info "Exporting APK..."

  # Find APK with preference order: universal -> arm64-v8a -> any release
  apk=""

  # 1. Look for universal APK first
  apk="$(find "$CODEBASE_DIR" -type f -path "*/build/outputs/apk/**/release/*-universal-*.apk" -print 2>/dev/null | head -n 1 || true)"

  # 2. If no universal, look for arm64-v8a
  if [ -z "$apk" ]; then
    apk="$(find "$CODEBASE_DIR" -type f -path "*/build/outputs/apk/**/release/*arm64-v8a*-release.apk" -print 2>/dev/null | head -n 1 || true)"
  fi

  # 3. Fallback to any release APK
  if [ -z "$apk" ]; then
    apk="$(find "$CODEBASE_DIR" -type f -path "*/build/outputs/apk/**/release/*-release.apk" -print 2>/dev/null | head -n 1 || true)"
  fi

  # 4. Final fallback - any APK in release directory
  if [ -z "$apk" ]; then
    apk="$(find "$CODEBASE_DIR" -type f -path "*/build/outputs/apk/release/*.apk" -print 2>/dev/null | head -n 1 || true)"
  fi

  [ -n "$apk" ] || {
    warn "No APK found. Searching all APK locations:"
    find "$CODEBASE_DIR" -type f -name "*.apk" -print 2>/dev/null | head -10 | sed 's/^/[found] /' || true
    error "No release APK found."
  }

  mkdir -p "$APK_DIR"
  out="$APK_DIR/gotify.apk"
  cp -f "$apk" "$out"

  info "APK ready: $out"
  printf 'APK_PATH=%s\n' "$out"
}

# --- Main ---
main() {
  info "Gotify Android build starting..."
  check_prerequisites
  print_toolchain_info
  setup_environment
  validate_target_sdk
  build_gotify
  export_artifacts
  info "✅ Build complete: $APK_DIR/gotify.apk"
}

main "$@"