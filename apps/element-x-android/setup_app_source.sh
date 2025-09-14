#!/usr/bin/env bash
# Optimized Element X Android build (macOS-friendly, Bash 3.2 safe)
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_PREFIX="[setup_app_source]"
CODEBASE_DIR="$SCRIPT_DIR/codebase"
DIST_DIR="$SCRIPT_DIR/dist"

info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*" >&2; }
error(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*"; exit 1; }

# --- Helpers (BSD/macOS safe) ------------------------------------------------
cpus() {
  if command -v sysctl >/dev/null 2>&1; then sysctl -n hw.ncpu 2>/dev/null || echo 2; else echo 2; fi
}
total_mem_mb() {
  if command -v sysctl >/dev/null 2>&1; then
    # bytes -> MB (integer)
    echo $(( $(sysctl -n hw.memsize 2>/dev/null || echo 2147483648) / 1024 / 1024 ))
  else
    echo 2048
  fi
}

# --- 1) Checks ---------------------------------------------------------------
check_prerequisites() {
  command -v java >/dev/null 2>&1 || error "Java not found on PATH"
  [ -d "$CODEBASE_DIR" ] || error "Codebase not found: $CODEBASE_DIR"
  [ -f "$CODEBASE_DIR/gradlew" ] || error "gradlew missing in $CODEBASE_DIR"

  # Prefer macOS JDK resolver
  if command -v /usr/libexec/java_home >/dev/null 2>&1; then
    # Prefer JDK 17 if present; fallback to default
    JAVA_HOME="${JAVA_HOME:-$((/usr/libexec/java_home -v 17 2>/dev/null) || /usr/libexec/java_home)}" || true
  fi
  if [ -z "${JAVA_HOME:-}" ]; then
    JAVA_HOME="$(java -XshowSettings:properties -version 2>&1 | awk -F'= ' '/^\s*java\.home =/ {print $2; exit}')" || true
  fi
  export JAVA_HOME="${JAVA_HOME:-}"

  # Android SDK detection (mac common first)
  if [ -z "${ANDROID_HOME:-}" ] && [ -z "${ANDROID_SDK_ROOT:-}" ]; then
    if   [ -d "${HOME}/Library/Android/sdk" ]; then ANDROID_HOME="${HOME}/Library/Android/sdk"
    elif [ -d "${HOME}/.android-sdk" ]; then ANDROID_HOME="${HOME}/.android-sdk"
    elif [ -d "/usr/local/share/android-sdk" ]; then ANDROID_HOME="/usr/local/share/android-sdk"
    elif [ -d "/usr/local/lib/android/sdk" ]; then ANDROID_HOME="/usr/local/lib/android/sdk"
    fi
    export ANDROID_HOME="${ANDROID_HOME:-}"
  fi
  export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-}}"

  # Basic sanity (don’t hard fail if SDK not set; Gradle can still resolve with AGP)
  if [ -z "${ANDROID_SDK_ROOT:-}" ]; then
    warn "ANDROID_SDK_ROOT not set; trying to proceed (AGP may bootstrap)."
  fi
}

# --- 2) Environment ----------------------------------------------------------
setup_environment() {
  info "Configuring build environment…"

  # Reasonable heap sizing for mac laptops; keep metaspace modest.
  # Use more heap if plenty of RAM is available.
  MEM_MB="$(total_mem_mb)"
  if [ "$MEM_MB" -ge 16384 ]; then
    JVM_HEAP="-Xmx4096m"
    KOTLIN_HEAP="-Xmx1536m"
  elif [ "$MEM_MB" -ge 8192 ]; then
    JVM_HEAP="-Xmx3072m"
    KOTLIN_HEAP="-Xmx1024m"
  else
    JVM_HEAP="-Xmx2048m"
    KOTLIN_HEAP="-Xmx768m"
  fi

  export GRADLE_OPTS="$JVM_HEAP -XX:MaxMetaspaceSize=384m -Dfile.encoding=UTF-8 -Djava.awt.headless=true"

  # local.properties: write sdk.dir only if not already present
  if [ -n "${ANDROID_SDK_ROOT:-}" ]; then
    if [ ! -f "$CODEBASE_DIR/local.properties" ] || ! grep -q '^sdk.dir=' "$CODEBASE_DIR/local.properties" 2>/dev/null; then
      printf 'sdk.dir=%s\n' "$ANDROID_SDK_ROOT" > "$CODEBASE_DIR/local.properties"
    fi
  fi

  # Append (or update) a guarded gradle.properties block to enable speed-ups for warm builds
  GP="$CODEBASE_DIR/gradle.properties"
  BLOCK_START="# >>> chatgpt-optimized BEGIN"
  BLOCK_END="# <<< chatgpt-optimized END"
  if [ -f "$GP" ] && grep -q "$BLOCK_START" "$GP" 2>/dev/null; then
    # Remove old block first (BSD sed compatible: use temp file)
    tmpf="$GP.tmp.$$"
    awk -v s="$BLOCK_START" -v e="$BLOCK_END" '
      $0==s {skip=1; next}
      $0==e {skip=0; next}
      skip!=1 {print}
    ' "$GP" > "$tmpf" && mv "$tmpf" "$GP"
  fi

  cat >> "$GP" <<EOF
$BLOCK_START
# Performance-focused defaults (safe for macOS + Bash 3.2)
org.gradle.jvmargs=${JVM_HEAP} -XX:MaxMetaspaceSize=384m -Dfile.encoding=UTF-8
org.gradle.parallel=true
org.gradle.workers.max=$(cpus)
org.gradle.caching=true
org.gradle.configuration-cache=true
org.gradle.daemon=true

# AndroidX + faster resource linking
android.useAndroidX=true
android.nonTransitiveRClass=true

# Kotlin incremental for warm builds
kotlin.incremental=true
kotlin.daemon.jvmargs=${KOTLIN_HEAP},-XX:MaxMetaspaceSize=384m

# Keep experiments off unless you know you need them
android.experimental.enableTestFixtures=false
$BLOCK_END
EOF

  chmod +x "$CODEBASE_DIR/gradlew" 2>/dev/null || true
  mkdir -p "$DIST_DIR"
}

# --- 3) Build ----------------------------------------------------------------
build_element_x() {
  info "Starting optimized build…"

  # Use daemon for mac (fast warm builds). In CI (CI=true), avoid daemon & config cache.
  CI_MODE="${CI:-false}"
  MAX_WORKERS="$(cpus)"

  cd "$CODEBASE_DIR"

  if [ "$CI_MODE" = "true" ]; then
    ./gradlew :app:assembleFdroidDebug \
      --no-daemon \
      --no-configuration-cache \
      --build-cache \
      --max-workers="$MAX_WORKERS" \
      --console=plain \
      -Dorg.gradle.parallel=true \
      -Dorg.gradle.workers.max="$MAX_WORKERS" \
      -Dkotlin.incremental=true \
      -x test -x testClasses -x connectedCheck -x deviceCheck -x lint -x lintDebug
  else
    ./gradlew :app:assembleFdroidDebug \
      --daemon \
      --build-cache \
      --configuration-cache \
      --max-workers="$MAX_WORKERS" \
      --console=plain \
      -Dorg.gradle.parallel=true \
      -Dorg.gradle.workers.max="$MAX_WORKERS" \
      -Dkotlin.incremental=true \
      -x test -x testClasses -x connectedCheck -x deviceCheck -x lint -x lintDebug
  fi

  cd - >/dev/null
}

# --- 4) Export ---------------------------------------------------------------
export_artifacts() {
  info "Exporting APK…"
  # Pick newest debug APK under outputs (BSD/macOS safe)
  # Avoid null delimiters for Bash 3.2; rely on ls -t fallback.
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

# --- 5) Optional cleanup -----------------------------------------------------
lightweight_cleanup() {
  # Only stop daemons in CI. On mac dev, keep daemon warm for speed.
  if [ "${CI:-false}" = "true" ]; then
    (cd "$CODEBASE_DIR" && ./gradlew --stop >/dev/null 2>&1 || true)
  fi
}

# --- Main --------------------------------------------------------------------
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
