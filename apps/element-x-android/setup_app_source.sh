#!/usr/bin/env bash
# Build Element X from source and EXPORT APKs into dist/ (no install, Gradle 9/AGP 8.3+ safe)
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_PREFIX="[setup_app_source]"
LOG_FILE="${SCRIPT_DIR}/setup_app_source.log"
CODEBASE_DIR="$SCRIPT_DIR/codebase"
DIST_DIR="$SCRIPT_DIR/dist"

exec > >(tee -a "$LOG_FILE") 2>&1
info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*"; }
error(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*"; exit 1; }
trap 'rc=$?; echo "[ERROR] setup_app_source.sh failed at line $LINENO (exit $rc)"; exit $rc' ERR

check_prerequisites() {
  info "Checking prerequisites (Java 17 + Android SDK path)..."
  command -v java >/dev/null 2>&1 || error "Java not found. Install Java 17."
  [[ -d "$CODEBASE_DIR" ]] || error "Codebase not found: $CODEBASE_DIR"
  [[ -f "$CODEBASE_DIR/gradlew" ]] || error "gradlew missing in $CODEBASE_DIR"

  # Expect SDK already provisioned (we do not install here)
  if [[ -z "${ANDROID_HOME:-}" && -z "${ANDROID_SDK_ROOT:-}" ]]; then
    if [[ -d "${HOME}/.android-sdk" ]]; then
      export ANDROID_HOME="${HOME}/.android-sdk"
    elif [[ -d "/usr/local/lib/android/sdk" ]]; then
      export ANDROID_HOME="/usr/local/lib/android/sdk"
    fi
  fi
  export ANDROID_SDK_ROOT="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}"
  if [[ -n "${ANDROID_SDK_ROOT:-}" ]]; then
    info "Using ANDROID_SDK_ROOT=$ANDROID_SDK_ROOT"
  else
    warn "ANDROID_SDK_ROOT not set; Gradle will attempt to locate SDK."
  fi
}

setup_environment() {
  info "Configuring CI-friendly build environment..."

  # JAVA_HOME
  if [[ -d "/usr/lib/jvm/java-17-openjdk" ]]; then
    export JAVA_HOME="/usr/lib/jvm/java-17-openjdk"
  elif [[ -d "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home" ]]; then
    export JAVA_HOME="/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"
  else
    export JAVA_HOME="$(java -XshowSettings:properties -version 2>&1 | awk -F'= ' '/java.home/ {print $2}')"
  fi
  export PATH="$JAVA_HOME/bin:$PATH"

  # Modest memory & workers for GitHub runners (Gradle 9 OK)
  export GRADLE_OPTS="-Xmx2g -XX:+UseG1GC -XX:+UseStringDeduplication"
  export org_gradle_daemon="false"
  export org_gradle_caching="true"
  export org_gradle_configuration_cache="true"
  export org_gradle_workers_max="2"
  # Avoid VFS watching memory overhead in CI
  export org_gradle_unsafe_watch_fs="false"

  # Point AGP to SDK (no install)
  if [[ -n "${ANDROID_SDK_ROOT:-}" ]]; then
    echo "sdk.dir=${ANDROID_SDK_ROOT}" > "$CODEBASE_DIR/local.properties"
    export PATH="$ANDROID_SDK_ROOT/platform-tools:$ANDROID_SDK_ROOT/cmdline-tools/latest/bin:$PATH"
  fi

  # Ensure gradle.properties has safe CI defaults (idempotent)
  GP="$CODEBASE_DIR/gradle.properties"; touch "$GP"
  grep -q '^org.gradle.jvmargs=' "$GP" || echo "org.gradle.jvmargs=-Xmx2g -XX:+UseG1GC -XX:+UseStringDeduplication" >> "$GP"
  grep -q '^org.gradle.workers.max=' "$GP" || echo "org.gradle.workers.max=2" >> "$GP"
  grep -q '^org.gradle.daemon=' "$GP" || echo "org.gradle.daemon=false" >> "$GP"
  grep -q '^org.gradle.caching=' "$GP" || echo "org.gradle.caching=true" >> "$GP"
  grep -q '^org.gradle.configuration-cache=' "$GP" || echo "org.gradle.configuration-cache=true" >> "$GP"
  grep -q '^kotlin.compiler.execution.strategy=' "$GP" || echo "kotlin.compiler.execution.strategy=in-process" >> "$GP"
  grep -q '^kotlin.daemon.useFallbackStrategy=' "$GP" || echo "kotlin.daemon.useFallbackStrategy=false" >> "$GP"

  # >>> Gradle 9 / AGP 8.3+ compatibility (remove deprecated dexing flag)
  # Remove any 'android.enableDexingArtifactTransform' from all likely locations
  sanitize_gradle_properties "$GP"
  # Also check common parent/root and user gradle.properties if present (best-effort)
  for p in "$SCRIPT_DIR/gradle.properties" "$SCRIPT_DIR/../gradle.properties" "$SCRIPT_DIR/../../gradle.properties" "$HOME/.gradle/gradle.properties"; do
    [[ -f "$p" ]] && sanitize_gradle_properties "$p" || true
  done
  # Add the recommended replacement (harmless if unused)
  ensure_line "$GP" "android.useFullClasspathForDexingTransform=true"
  # <<<

  chmod +x "$CODEBASE_DIR/gradlew" || true
  mkdir -p "$DIST_DIR"
  find "$DIST_DIR" -maxdepth 1 -type f -name "*debug.apk" -delete 2>/dev/null || true

  info "Environment configured."
}

sanitize_gradle_properties() {
  local file="$1"
  # If the file contains the deprecated option, comment it out
  if grep -q '^[[:space:]]*android\.enableDexingArtifactTransform' "$file"; then
    info "Removing deprecated 'android.enableDexingArtifactTransform' from $file"
    awk '!match($0, /^[[:space:]]*android\.enableDexingArtifactTransform[[:space:]]*=/)' "$file" > "${file}.tmp" && mv "${file}.tmp" "$file"
  fi
}

ensure_line() {
  local file="$1" line="$2"
  grep -q -F "$line" "$file" 2>/dev/null || echo "$line" >> "$file"
}

lightweight_cleanup() {
  info "Lightweight cleanup (preserving Gradle caches)..."
  pushd "$CODEBASE_DIR" >/dev/null
  ./gradlew --stop >/dev/null 2>&1 || true
  # Do NOT touch ~/.gradle or .gradle caches
  find . -path "*/build/tmp" -type d -mtime +3 -prune -exec rm -rf {} + 2>/dev/null || true
  popd >/dev/null
}

build_element_x() {
  info "Building Element X (assembleFdroidDebug)..."
  pushd "$CODEBASE_DIR" >/dev/null

  ./gradlew :app:assembleFdroidDebug \
    --stacktrace \
    --console=plain \
    --configuration-cache \
    -Dorg.gradle.workers.max=2 \
    -Dkotlin.incremental=true \
    -x test -x testClasses -x connectedCheck -x deviceCheck \
    -x detekt -x ktlintCheck -x ktlintFormat

  popd >/dev/null
  info "Build finished."
}

export_artifacts() {
  info "Exporting APKs to $DIST_DIR ..."
  local outdir="$CODEBASE_DIR/app/build/outputs/apk/fdroid/debug"
  local found=0

  if [[ -d "$outdir" ]]; then
    while IFS= read -r -d '' apk; do
      cp -f "$apk" "$DIST_DIR/"
      found=1
    done < <(find "$outdir" -maxdepth 1 -type f -name "*.apk" -print0 2>/dev/null || true)
  fi

  if [[ $found -eq 0 ]]; then
    while IFS= read -r -d '' apk; do
      cp -f "$apk" "$DIST_DIR/"
      found=1
    done < <(find "$CODEBASE_DIR" -path "*/build/outputs/apk/*/debug/*.apk" -print0 2>/dev/null || true)
  fi

  [[ $found -gt 0 ]] || error "No debug APKs found. Check Gradle logs."

  if ! ls "$DIST_DIR"/*universal*debug.apk >/dev/null 2>&1; then
    first_apk="$(ls -1 "$DIST_DIR"/*debug.apk | head -n1)"
    cp -f "$first_apk" "$DIST_DIR/elementx-universal-debug.apk"
  fi

  info "Exported APKs:"
  (cd "$DIST_DIR" && ls -lh *debug.apk 2>/dev/null || true)
  command -v shasum >/dev/null 2>&1 && shasum -a 256 "$DIST_DIR"/*debug.apk 2>/dev/null || true
}

main() {
  info "Element X Android Setup (build-only)"
  echo "===================================="

  check_prerequisites
  setup_environment
  lightweight_cleanup
  build_element_x
  export_artifacts
  lightweight_cleanup

  echo ""
  echo "=========================================="
  info "✅ APK(s) ready in: $DIST_DIR"
  info "Next step: run your setup.sh to install/launch."
  echo "=========================================="
  echo ""
}

main "$@"
