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
cpus() {
  if command -v sysctl >/dev/null 2>&1; then sysctl -n hw.ncpu 2>/dev/null || echo 2; else echo 2; fi
}
total_mem_mb() {
  if command -v sysctl >/dev/null 2>&1; then
    echo $(( $(sysctl -n hw.memsize 2>/dev/null || echo 2147483648) / 1024 / 1024 ))
  else
    echo 2048
  fi
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
    if   [ -d "${HOME}/Library/Android/sdk" ]; then ANDROID_HOME="${HOME}/Library/Android/sdk"
    elif [ -d "${HOME}/.android-sdk" ]; then ANDROID_HOME="${HOME}/.android-sdk"
    elif [ -d "/usr/local/share/android-sdk" ]; then ANDROID_HOME="/usr/local/share/android-sdk"
    elif [ -d "/usr/local/lib/android/sdk" ]; then ANDROID_HOME="/usr/local/lib/android/sdk"
    fi
    export ANDROID_HOME="${ANDROID_HOME:-}"
  fi
  export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-}}"

  if [ -z "${ANDROID_SDK_ROOT:-}" ]; then
    warn "ANDROID_SDK_ROOT not set; proceeding (AGP may bootstrap)."
  fi

  chmod +x "$CODEBASE_DIR/gradlew" 2>/dev/null || true
  mkdir -p "$DIST_DIR"
}

# --- 2) Environment ---
setup_environment() {
  info "Configuring build environment…"

  MEM_MB="$(total_mem_mb)"
  if [ "$MEM_MB" -ge 16384 ]; then
    JVM_HEAP="-Xmx4096m"; KOTLIN_HEAP="-Xmx1536m"; META_MB=512
  elif [ "$MEM_MB" -ge 8192 ]; then
    JVM_HEAP="-Xmx3072m"; KOTLIN_HEAP="-Xmx1024m"; META_MB=384
  else
    JVM_HEAP="-Xmx2048m"; KOTLIN_HEAP="-Xmx768m";  META_MB=384
  fi

  export GRADLE_OPTS="$JVM_HEAP -XX:MaxMetaspaceSize=${META_MB}m -Dfile.encoding=UTF-8 -Djava.awt.headless=true"
  KOTLIN_DAEMON_JVMARGS="${KOTLIN_HEAP} -XX:MaxMetaspaceSize=${META_MB}m -XX:-UseParallelGC"

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
    awk -v s="$BS" -v e="$BE" '
      $0==s {skip=1; next}
      $0==e {skip=0; next}
      skip!=1 {print}
    ' "$GP" > "$tmpf" && mv "$tmpf" "$GP"
  fi

  {
    echo "$BS"
    echo "org.gradle.jvmargs=${JVM_HEAP} -XX:MaxMetaspaceSize=${META_MB}m -Dfile.encoding=UTF-8"
    echo "org.gradle.parallel=true"
    echo "org.gradle.workers.max=$(cpus)"
    echo "org.gradle.caching=true"
    echo "org.gradle.configuration-cache=true"
    echo "org.gradle.daemon=true"
    echo
    echo "android.useAndroidX=true"
    echo "android.nonTransitiveRClass=true"
    echo
    echo "kotlin.incremental=true"
    echo "kotlin.incremental.useClasspathSnapshot=true"
    # IMPORTANT: space-separated, no commas
    echo "kotlin.daemon.jvmargs=${KOTLIN_DAEMON_JVMARGS}"
    echo
    echo "systemProp.org.gradle.internal.http.connectionTimeout=60000"
    echo "systemProp.org.gradle.internal.http.socketTimeout=120000"
    echo "$BE"
  } >> "$GP"

  # Remove experimental lint override if present (it slows resolution)
  if [ -f "$GP" ] && grep -q '^android\.experimental\.lint\.version=' "$GP" 2>/dev/null; then
    tmpf="$GP.tmp.$$"
    grep -v '^android\.experimental\.lint\.version=' "$GP" > "$tmpf" && mv "$tmpf" "$GP"
    info "Removed experimental lint override from gradle.properties"
  fi
}

# --- 3) Build ---
build_element_x() {
  info "Starting optimized build…"

  MAX_WORKERS="$(cpus)"
  CI_MODE="${CI:-false}"
  CONSOLE_FLAG="--console=rich"

  # Optional ABI limiting for faster packaging: export TARGET_ABI=arm64-v8a or x86_64
  if [ -n "${TARGET_ABI:-}" ]; then
    info "Limiting ABI to ${TARGET_ABI}"
    ABI_PROP="-Dorg.gradle.project.android.injected.ndk.abiFilters=${TARGET_ABI}"
  else
    ABI_PROP=""
  fi

  cd "$CODEBASE_DIR"

  # First attempt: daemon + config cache (fastest on mac)
  set +e
  ./gradlew :app:assembleFdroidDebug \
    $CONSOLE_FLAG \
    --build-cache \
    $( [ "$CI_MODE" = "true" ] && echo --no-daemon --no-configuration-cache || echo --daemon --configuration-cache ) \
    --max-workers="$MAX_WORKERS" \
    -Dorg.gradle.parallel=true \
    -Dorg.gradle.workers.max="$MAX_WORKERS" \
    -Dkotlin.incremental=true \
    -Dkotlin.daemon.jvmargs="${KOTLIN_DAEMON_JVMARGS}" \
    $ABI_PROP \
    -x test -x testClasses -x connectedCheck -x deviceCheck -x lint -x lintDebug
  rc=$?
  set -e

  if [ $rc -ne 0 ]; then
    warn "Daemon build failed (rc=$rc); retrying with in-process Kotlin compiler…"
    ./gradlew :app:assembleFdroidDebug \
      --no-daemon \
      --no-configuration-cache \
      --build-cache \
      --max-workers="$MAX_WORKERS" \
      --console=plain \
      -Dorg.gradle.parallel=true \
      -Dorg.gradle.workers.max="$MAX_WORKERS" \
      -Dkotlin.incremental=true \
      -Dkotlin.compiler.execution.strategy=in-process \
      -Dkotlin.daemon.useFallbackStrategy=false \
      -Dkotlin.daemon.jvmargs="${KOTLIN_DAEMON_JVMARGS}" \
      $ABI_PROP \
      -x test -x testClasses -x connectedCheck -x deviceCheck -x lint -x lintDebug
  fi

  cd - >/dev/null
}

# --- 4) Export ---
export_artifacts() {
  info "Exporting APK…"
  newest_apk=""
  # shellcheck disable=SC2010
  newest_apk="$(ls -t "$CODEBASE_DIR"/app/build/outputs/apk/*/debug/*.apk 2>/dev/null | head -n 1 || true)"
  if [ -z "$newest_apk" ]; then
    newest_apk="$(find "$CODEBASE_DIR" -type f -path "*/build/outputs/apk/*/debug/*.apk" -print 2>/dev/null | xargs ls -t 2>/dev/null | head -n 1 || true)"
  fi
  [ -n "$newest_apk" ] || error "No debug APK found in build outputs."
  cp -f "$newest_apk" "$DIST_DIR/elementx-universal-debug.apk"
  info "APK ready: $DIST_DIR/elementx-universal-debug.apk"
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
  info "✅ Done: $DIST_DIR/elementx-universal-debug.apk"
}

main "$@"
