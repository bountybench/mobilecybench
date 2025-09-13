#!/usr/bin/env bash
# Build Element X APK into dist/ with minimal RAM footprint (Gradle 9/AGP 8.3+ safe)
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

  # We don't install the SDK here; we just try to point AGP to it if present
  if [[ -z "${ANDROID_HOME:-}" && -z "${ANDROID_SDK_ROOT:-}" ]]; then
    if [[ -d "${HOME}/.android-sdk" ]]; then
      export ANDROID_HOME="${HOME}/.android-sdk"
    elif [[ -d "/usr/local/lib/android/sdk" ]]; then
      export ANDROID_HOME="/usr/local/lib/android/sdk"
    fi
  fi
  export ANDROID_SDK_ROOT="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}"
  [[ -n "${ANDROID_SDK_ROOT:-}" ]] && info "Using ANDROID_SDK_ROOT=$ANDROID_SDK_ROOT" || warn "ANDROID_SDK_ROOT not set; Gradle will try to locate the SDK."
}

sanitize_gradle_properties() {
  local file="$1"
  [[ -f "$file" ]] || return 0
  # Remove deprecated flag that AGP 8.3+ errors on
  if grep -q '^[[:space:]]*android\.enableDexingArtifactTransform' "$file"; then
    info "Removing deprecated 'android.enableDexingArtifactTransform' from $file"
    awk '!match($0, /^[[:space:]]*android\.enableDexingArtifactTransform[[:space:]]*=/)' "$file" > "${file}.tmp" && mv "${file}.tmp" "$file"
  fi
}

setup_environment() {
  info "Configuring ultra-low-RAM build environment..."

  # JAVA_HOME
  if [[ -d "/usr/lib/jvm/java-17-openjdk" ]]; then
    export JAVA_HOME="/usr/lib/jvm/java-17-openjdk"
  elif [[ -d "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home" ]]; then
    export JAVA_HOME="/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"
  else
    export JAVA_HOME="$(java -XshowSettings:properties -version 2>&1 | awk -F'= ' '/java.home/ {print $2}')"
  fi
  export PATH="$JAVA_HOME/bin:$PATH"

  # SUPER CONSERVATIVE: 2G heap, small metaspace, single worker, no daemon, no parallel, no config cache
  export GRADLE_OPTS="-Xmx2048m -XX:MaxMetaspaceSize=384m -XX:+UseG1GC -XX:+UseStringDeduplication -Dfile.encoding=UTF-8"
  export org_gradle_daemon="false"
  export org_gradle_parallel="false"
  export org_gradle_workers_max="1"
  export org_gradle_caching="true"            # cache is fine; doesn't spike RAM
  export org_gradle_configuration_cache="false" # disable to keep memory flatter
  export org_gradle_unsafe_watch_fs="false"

  # Kotlin in-process → no extra daemon JVM
  GP="$CODEBASE_DIR/gradle.properties"; touch "$GP"
  echo "sdk.dir=${ANDROID_SDK_ROOT:-}" > "$CODEBASE_DIR/local.properties"
  export PATH="$ANDROID_SDK_ROOT/platform-tools:$ANDROID_SDK_ROOT/cmdline-tools/latest/bin:$PATH"

  # Idempotent props
  grep -q '^org.gradle.jvmargs=' "$GP" || echo "org.gradle.jvmargs=-Xmx2048m -XX:MaxMetaspaceSize=384m -XX:+UseG1GC -XX:+UseStringDeduplication -Dfile.encoding=UTF-8" >> "$GP"
  grep -q '^org.gradle.workers.max=' "$GP" || echo "org.gradle.workers.max=1" >> "$GP"
  grep -q '^org.gradle.daemon=' "$GP" || echo "org.gradle.daemon=false" >> "$GP"
  grep -q '^org.gradle.parallel=' "$GP" || echo "org.gradle.parallel=false" >> "$GP"
  grep -q '^org.gradle.caching=' "$GP" || echo "org.gradle.caching=true" >> "$GP"
  grep -q '^org.gradle.configuration-cache=' "$GP" || echo "org.gradle.configuration-cache=false" >> "$GP"
  grep -q '^kotlin.compiler.execution.strategy=' "$GP" || echo "kotlin.compiler.execution.strategy=in-process" >> "$GP"
  grep -q '^kotlin.daemon.useFallbackStrategy=' "$GP" || echo "kotlin.daemon.useFallbackStrategy=false" >> "$GP"

  # Gradle 9 / AGP 8.3+ safety: strip deprecated dexing flag anywhere it might lurk
  sanitize_gradle_properties "$GP"
  sanitize_gradle_properties "$SCRIPT_DIR/gradle.properties"
  sanitize_gradle_properties "$SCRIPT_DIR/../gradle.properties"
  sanitize_gradle_properties "$SCRIPT_DIR/../../gradle.properties"
  sanitize_gradle_properties "$HOME/.gradle/gradle.properties" || true

  chmod +x "$CODEBASE_DIR/gradlew" || true
  mkdir -p "$DIST_DIR"
  find "$DIST_DIR" -maxdepth 1 -type f -name "*debug.apk" -delete 2>/dev/null || true

  # Helpful visibility in CI logs
  info "Java: $(java -version 2>&1 | head -n1)"
  info "GRADLE_OPTS=$GRADLE_OPTS"
  info "Workers: 1, Parallel: off, Daemon: off, ConfigCache: off"
}

lightweight_cleanup() {
  info "Lightweight cleanup (preserving caches)..."
  pushd "$CODEBASE_DIR" >/dev/null
  ./gradlew --stop >/dev/null 2>&1 || true
  find . -path "*/build/tmp" -type d -mtime +3 -prune -exec rm -rf {} + 2>/dev/null || true
  popd >/dev/null
}

build_element_x() {
  info "Building Element X (assembleFdroidDebug) with single worker..."
  pushd "$CODEBASE_DIR" >/dev/null

  # Extra hard caps via command line, matching manager guidance
  ./gradlew :app:assembleFdroidDebug \
    --stacktrace \
    --console=plain \
    --no-daemon \
    --no-parallel \
    --max-workers=1 \
    -Dorg.gradle.workers.max=1 \
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
      cp -f "$apk" "$DIST_DIR/"; found=1
    done < <(find "$CODEBASE_DIR" -path "*/build/outputs/apk/*/debug/*.apk" -print0 2>/dev/null || true)
  fi
  [[ $found -gt 0 ]] || error "No debug APKs found. Check Gradle logs."

  if ! ls "$DIST_DIR"/*universal*debug.apk >/dev/null 2>&1; then
    first_apk="$(ls -1 "$DIST_DIR"/*debug.apk | head -n1)"
    cp -f "$first_apk" "$DIST_DIR/elementx-universal-debug.apk"
  fi

  info "Exported APKs:"
  (cd "$DIST_DIR" && ls -lh *debug.apk 2>/dev/null || true)
}

main() {
  info "Element X Android Setup (build-only)"
  echo "===================================="

  check_prerequisites
  setup_environment
  lightweight_cleanup
  # Optional: show free memory before & after to diagnose 143s
  command -v free >/dev/null 2>&1 && free -h || true
  build_element_x
  command -v free >/dev/null 2>&1 && free -h || true
  export_artifacts
  lightweight_cleanup

  echo ""
  echo "=========================================="
  info "✅ APK(s) ready in: $DIST_DIR"
  info "Next step: run setup.sh to install/launch."
  echo "=========================================="
  echo ""
}

main "$@"
