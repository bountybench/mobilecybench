#!/usr/bin/env bash
# Optimized Element X Android build (macOS-friendly, Bash 3.2 safe, Gradle 9-ready)
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_PREFIX="[setup_app_source]"
CODEBASE_DIR="$SCRIPT_DIR/codebase"
DIST_DIR="$SCRIPT_DIR/dist"

info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*" >&2; }
error(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*"; exit 1; }

# --- Helpers (BSD/macOS safe) ---
cpus(){ command -v sysctl >/dev/null 2>&1 && sysctl -n hw.ncpu 2>/dev/null || echo 2; }
total_mem_mb(){ command -v sysctl >/dev/null 2>&1 && echo $(( $(sysctl -n hw.memsize 2>/dev/null || echo 2147483648) / 1024 / 1024 )) || echo 2048; }

pick_build_task() {
  cd "$CODEBASE_DIR"
  # Try your preferred task first; then fallbacks
  for t in :app:assembleFdroidDebug :app:assembleDebug assembleFdroidDebug assembleDebug; do
    ./gradlew -m "$t" --quiet >/dev/null 2>&1 && { echo "$t"; cd - >/dev/null; return 0; }
  done
  cd - >/dev/null
  echo ""
  return 1
}

# --- 1) Checks ---
check_prerequisites() {
  command -v java >/dev/null 2>&1 || error "Java not found on PATH"
  [ -d "$CODEBASE_DIR" ] || error "Codebase not found: $CODEBASE_DIR"
  [ -f "$CODEBASE_DIR/gradlew" ] || error "gradlew missing in $CODEBASE_DIR"

  # Prefer JDK 17 on macOS
  if command -v /usr/libexec/java_home >/dev/null 2>&1; then
    JAVA_HOME="${JAVA_HOME:-$((/usr/libexec/java_home -v 17 2>/dev/null) || /usr/libexec/java_home)}" || true
  fi
  if [ -z "${JAVA_HOME:-}" ]; then
    JAVA_HOME="$(java -XshowSettings:properties -version 2>&1 | awk -F'= ' '/^\s*java\.home =/ {print $2; exit}')" || true
  fi
  export JAVA_HOME="${JAVA_HOME:-}"

  # Android SDK detection (mac paths first)
  if [ -z "${ANDROID_HOME:-}" ] && [ -z "${ANDROID_SDK_ROOT:-}" ]; then
    for d in "$HOME/Library/Android/sdk" "$HOME/.android-sdk" "/usr/local/share/android-sdk" "/usr/local/lib/android/sdk"; do
      [ -d "$d" ] && ANDROID_HOME="$d" && break
    done
    export ANDROID_HOME="${ANDROID_HOME:-}"
  fi
  export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-}}"

  [ -n "${ANDROID_SDK_ROOT:-}" ] || warn "ANDROID_SDK_ROOT not set; proceeding (AGP may bootstrap)."

  chmod +x "$CODEBASE_DIR/gradlew" 2>/dev/null || true
  mkdir -p "$DIST_DIR"
}

# --- 2) Environment ---
setup_environment() {
  info "Configuring build environment…"

  MEM_MB="$(total_mem_mb)"
  if   [ "$MEM_MB" -ge 16384 ]; then JVM_HEAP="-Xmx4096m"; KOTLIN_HEAP="-Xmx1536m"; META_MB=512
  elif [ "$MEM_MB" -ge 8192  ]; then JVM_HEAP="-Xmx3072m"; KOTLIN_HEAP="-Xmx1024m"; META_MB=384
  else                               JVM_HEAP="-Xmx2048m"; KOTLIN_HEAP="-Xmx768m";  META_MB=384
  fi

  export GRADLE_OPTS="$JVM_HEAP -XX:MaxMetaspaceSize=${META_MB}m -Dfile.encoding=UTF-8 -Djava.awt.headless=true"
  KOTLIN_DAEMON_JVMARGS="${KOTLIN_HEAP} -XX:MaxMetaspaceSize=${META_MB}m -XX:-UseParallelGC"  # NOTE: spaces, not commas

  # Disable licensee plugin for faster builds
  export ORG_GRADLE_PROJECT_licensee_skip=true
  export ORG_GRADLE_PROJECT_licensee_enable=false
  export LICENSEE_SKIP=true

  # local.properties: set sdk.dir if missing
  if [ -n "${ANDROID_SDK_ROOT:-}" ]; then
    if [ ! -f "$CODEBASE_DIR/local.properties" ] || ! grep -q '^sdk.dir=' "$CODEBASE_DIR/local.properties" 2>/dev/null; then
      printf 'sdk.dir=%s\n' "$ANDROID_SDK_ROOT" > "$CODEBASE_DIR/local.properties"
    fi
  fi

  # Write/refresh guarded block in gradle.properties
  GP="$CODEBASE_DIR/gradle.properties"
  BS="# >>> chatgpt-optimized BEGIN"
  BE="# <<< chatgpt-optimized END"
  if [ -f "$GP" ] && grep -q "$BS" "$GP" 2>/dev/null; then
    tmpf="$GP.tmp.$$"
    awk -v s="$BS" -v e="$BE" '$0==s{skip=1;next} $0==e{skip=0;next} !skip{print}' "$GP" > "$tmpf" && mv "$tmpf" "$GP"
  fi

  {
    echo "$BS"
    echo "org.gradle.jvmargs=${JVM_HEAP} -XX:MaxMetaspaceSize=${META_MB}m -Dfile.encoding=UTF-8"
    echo "org.gradle.parallel=true"
    echo "org.gradle.workers.max=$(cpus)"
    echo "org.gradle.caching=true"
    echo "org.gradle.configuration-cache=true"
    echo "org.gradle.daemon=true"
    echo "org.gradle.vfs.watch=true"
    echo
    echo "android.useAndroidX=true"
    echo "android.nonTransitiveRClass=true"
    echo
    echo "kotlin.incremental=true"
    echo "kotlin.incremental.useClasspathSnapshot=true"
    echo "kotlin.daemon.jvmargs=${KOTLIN_DAEMON_JVMARGS}"
    echo
    echo "systemProp.org.gradle.internal.http.connectionTimeout=60000"
    echo "systemProp.org.gradle.internal.http.socketTimeout=120000"
    echo "$BE"
  } >> "$GP"

  # Remove experimental lint override if present (prevents slow snapshot resolves)
  if [ -f "$GP" ] && grep -q '^android\.experimental\.lint\.version=' "$GP" 2>/dev/null; then
    tmpf="$GP.tmp.$$"; grep -v '^android\.experimental\.lint\.version=' "$GP" > "$tmpf" && mv "$tmpf" "$GP"
    info "Removed experimental lint override from gradle.properties"
  fi
}

# --- 3) Build ---
build_element_x() {
  info "Using fdroid debug build task…"
  TASK=":app:assembleFdroidDebug"

  info "Starting optimized build: $TASK"
  MAX_WORKERS="$(cpus)"
  CI_MODE="${CI:-false}"
  CONSOLE_FLAG="--console=rich"

  # ABI pin for emulator speed (arm64-v8a). If you ever need x86_64: TARGET_ABI=x86_64
  ABI="${TARGET_ABI:-arm64-v8a}"
  ABI_PROPS="-Dorg.gradle.project.android.injected.ndk.abiFilters=${ABI} -Pandroid.injected.build.abi=${ABI}"

  cd "$CODEBASE_DIR"

  set +e
  ./gradlew "$TASK" \
    $CONSOLE_FLAG \
    --build-cache \
    $( [ "$CI_MODE" = "true" ] && echo --no-daemon --no-configuration-cache || echo --daemon --configuration-cache ) \
    --max-workers="$MAX_WORKERS" \
    -Dorg.gradle.parallel=true \
    -Dorg.gradle.workers.max="$MAX_WORKERS" \
    -Dkotlin.incremental=true \
    -Dkotlin.incremental.useClasspathSnapshot=true \
    -Dkotlin.daemon.jvmargs="${KOTLIN_DAEMON_JVMARGS}" \
    -Dorg.gradle.vfs.watch=true \
    -Dorg.gradle.project.licensee.skip=true \
    -Dorg.gradle.project.licensee.enable=false \
    -Dlicensee.skip=true \
    $ABI_PROPS \
    -x test -x testClasses -x connectedCheck -x deviceCheck -x lint -x lintDebug
  rc=$?
  set -e

  if [ $rc -ne 0 ]; then
    warn "Daemon build failed (rc=$rc); retrying with in-process Kotlin…"
    ./gradlew "$TASK" \
      --no-daemon \
      --no-configuration-cache \
      --build-cache \
      --max-workers="$MAX_WORKERS" \
      --console=plain \
      -Dorg.gradle.parallel=true \
      -Dorg.gradle.workers.max="$MAX_WORKERS" \
      -Dkotlin.incremental=true \
      -Dkotlin.incremental.useClasspathSnapshot=true \
      -Dkotlin.compiler.execution.strategy=in-process \
      -Dkotlin.daemon.useFallbackStrategy=false \
      -Dkotlin.daemon.jvmargs="${KOTLIN_DAEMON_JVMARGS}" \
      -Dorg.gradle.project.licensee.skip=true \
      -Dorg.gradle.project.licensee.enable=false \
      -Dlicensee.skip=true \
      $ABI_PROPS \
      -x test -x testClasses -x connectedCheck -x deviceCheck -x lint -x lintDebug
  fi

  cd - >/dev/null
}

# --- 4) Export (robust) ---
export_artifacts() {
  info "Exporting APK…"

  # 1) Find APK in outputs or intermediates directories
  apk="$(find "$CODEBASE_DIR" -type f \( -path "*/build/outputs/apk/*/debug/*.apk" -o -path "*/build/intermediates/apk/*/debug/*.apk" \) -print 2>/dev/null | head -n 1 || true)"

  [ -n "$apk" ] || {
    warn "No APK found. Searching common locations:"
    find "$CODEBASE_DIR" -type f -name "*.apk" -print 2>/dev/null | head -5 | sed 's/^/[found] /' || true
    error "No debug APK found."
  }

  mkdir -p "$DIST_DIR"
  out="$DIST_DIR/elementx-arm64v8a-debug.apk"
  cp -f "$apk" "$out"
  info "APK ready: $out"
}

# --- 5) Optional cleanup ---
lightweight_cleanup() {
  if [ "${CI:-false}" = "true" ]; then
    (cd "$CODEBASE_DIR" && ./gradlew --stop >/dev/null 2>&1 || true)
  fi
}

# --- Main ---
main() {
  info "Optimized Element X build starting…"
  check_prerequisites
  setup_environment
  build_element_x
  export_artifacts
  lightweight_cleanup
  info "✅ Done: $DIST_DIR/elementx-arm64v8a-debug.apk"
}

main "$@"